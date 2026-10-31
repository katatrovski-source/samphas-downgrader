import os
import json
import time
import asyncio

import discord
from discord.ext import commands
from dotenv import load_dotenv

from .converter import (
    ConversionError,
    downgrade_aep,
    convert_ffx,
    detect_aep_version,
    detect_ffx_version,
)

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
GUILD_ID = os.getenv("GUILD_ID", "").strip()

ACCESS_ROLE_NAME = "Downgrade Access"
TEMP_ACCESS_FILE = "temp_access.json"

bot_active_until = 0
activation_task = None

temp_access_expirations = {}
temp_access_tasks = {}

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


VERSIONS = [
    "After Effects 2025", "After Effects 2024", "After Effects 2023",
    "After Effects 2022", "After Effects 2021", "After Effects 2020",
    "After Effects 2019", "After Effects 2018", "After Effects 2017",
    "After Effects 2015.3", "After Effects 2015", "After Effects 2014",
    "After Effects CS6"
]

FFX_VERSIONS = [
    "After Effects 2026",
    "After Effects 2025",
    "After Effects 2024 (experimental)",
    "After Effects 2023 (experimental)",
    "After Effects 2022 (experimental)",
    "After Effects 2021 (experimental)",
    "After Effects 2020 (experimental)",
]

DURATIONS = [
    discord.app_commands.Choice(name="10 minutes", value=600),
    discord.app_commands.Choice(name="30 minutes", value=1800),
    discord.app_commands.Choice(name="1 hour", value=3600),
    discord.app_commands.Choice(name="2 hours", value=7200),
    discord.app_commands.Choice(name="6 hours", value=21600),
    discord.app_commands.Choice(name="12 hours", value=43200),
    discord.app_commands.Choice(name="24 hours", value=86400),
]


# ------------------------------
# TEMPORARY ROLE STORAGE
# ------------------------------

def save_temp_access():
    with open(TEMP_ACCESS_FILE, "w", encoding="utf-8") as f:
        json.dump(temp_access_expirations, f)


def load_temp_access():
    global temp_access_expirations

    try:
        with open(TEMP_ACCESS_FILE, "r", encoding="utf-8") as f:
            temp_access_expirations = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        temp_access_expirations = {}


async def remove_temp_role_later(guild_id, user_id, expires_at):
    key = f"{guild_id}:{user_id}"

    try:
        await asyncio.sleep(max(0, expires_at - time.time()))

        if temp_access_expirations.get(key) != expires_at:
            return

        guild = bot.get_guild(guild_id)
        if guild is None:
            return

        role = discord.utils.get(guild.roles, name=ACCESS_ROLE_NAME)
        if role is None:
            return

        try:
            member = guild.get_member(user_id)
            if member is None:
                member = await guild.fetch_member(user_id)

            if role in member.roles:
                await member.remove_roles(
                    role,
                    reason="Temporary access expired"
                )

        except discord.NotFound:
            pass

    except asyncio.CancelledError:
        raise

    finally:
        if temp_access_expirations.get(key) == expires_at:
            temp_access_expirations.pop(key, None)
            save_temp_access()

        if temp_access_tasks.get(key) is asyncio.current_task():
            temp_access_tasks.pop(key, None)


# ------------------------------
# ACCESS CHECK
# ------------------------------

async def check_conversion_access(interaction):

    if time.time() >= bot_active_until:
        await interaction.response.send_message(
            "⏸️ The bot is currently inactive. "
            "An administrator must use `/activate` first.",
            ephemeral=True
        )
        return False

    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message(
            "This command can only be used inside the server.",
            ephemeral=True
        )
        return False

    role = discord.utils.get(
        interaction.guild.roles,
        name=ACCESS_ROLE_NAME
    )

    if role is None or role not in interaction.user.roles:
        await interaction.response.send_message(
            "🔒 You need the `Downgrade Access` role.",
            ephemeral=True
        )
        return False

    return True


# ------------------------------
# CONVERSION HANDLER
# ------------------------------

async def handle_conversion(interaction, attachment, target, kind):

    await interaction.response.defer(
        ephemeral=True,
        thinking=True
    )

    suffix = ".aep" if kind == "aep" else ".ffx"

    if not attachment.filename.lower().endswith(suffix):
        await interaction.followup.send(
            f"Please upload a `{suffix}` file.",
            ephemeral=True
        )
        return

    if attachment.size > 20 * 1024 * 1024:
        await interaction.followup.send(
            "The file exceeds the 20 MB limit.",
            ephemeral=True
        )
        return

    os.makedirs("uploads", exist_ok=True)
    os.makedirs("outputs", exist_ok=True)

    safe_name = os.path.basename(attachment.filename)

    source_path = os.path.join(
        "uploads",
        f"{interaction.id}_{safe_name}"
    )

    output_path = os.path.join(
        "outputs",
        f"{interaction.id}_{os.path.splitext(safe_name)[0]}_converted{suffix}"
    )

    try:
        await attachment.save(source_path)

        warning = ""

        if kind == "aep":
            source_version = detect_aep_version(source_path)

            downgrade_aep(
                source_path,
                output_path,
                target
            )

            result = (
                f"**AEP conversion:** "
                f"{source_version} → {target}"
            )

        else:
            raise ConversionError(
                "Use the /ffx command for FFX files."
            )

        await interaction.followup.send(
            content=result + warning,
            file=discord.File(output_path),
            ephemeral=True
        )

    except ConversionError as exc:
        await interaction.followup.send(
            f"**Could not convert:** {exc}",
            ephemeral=True
        )

    except Exception as exc:
        await interaction.followup.send(
            f"Unexpected error: `{type(exc).__name__}`",
            ephemeral=True
        )

    finally:
        for path in (source_path, output_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass


# ------------------------------
# ACTIVATE COMMAND
# ------------------------------

@bot.tree.command(
    name="activate",
    description="Activate conversion commands temporarily"
)
@discord.app_commands.checks.has_permissions(administrator=True)
@discord.app_commands.choices(duration=DURATIONS)
async def activate(
    interaction: discord.Interaction,
    duration: discord.app_commands.Choice[int]
):
    global bot_active_until, activation_task

    bot_active_until = time.time() + duration.value

    if activation_task and not activation_task.done():
        activation_task.cancel()

    async def deactivate_later():
        global bot_active_until

        await asyncio.sleep(duration.value)
        bot_active_until = 0

    activation_task = asyncio.create_task(deactivate_later())

    await interaction.response.send_message(
        f"✅ Conversion commands are now active for **{duration.name}**.",
        ephemeral=True
    )


# ------------------------------
# DEACTIVATE COMMAND
# ------------------------------

@bot.tree.command(
    name="deactivate",
    description="Deactivate conversion commands"
)
@discord.app_commands.checks.has_permissions(administrator=True)
async def deactivate(interaction: discord.Interaction):

    global bot_active_until, activation_task

    bot_active_until = 0

    if activation_task and not activation_task.done():
        activation_task.cancel()

    await interaction.response.send_message(
        "⏸️ Conversion commands have been deactivated.",
        ephemeral=True
    )


# ------------------------------
# TEMP ACCESS COMMAND
# ------------------------------

@bot.tree.command(
    name="tempaccess",
    description="Give a user temporary Downgrade Access"
)
@discord.app_commands.checks.has_permissions(administrator=True)
@discord.app_commands.choices(duration=DURATIONS)
async def tempaccess(
    interaction: discord.Interaction,
    user: discord.Member,
    duration: discord.app_commands.Choice[int]
):

    role = discord.utils.get(
        interaction.guild.roles,
        name=ACCESS_ROLE_NAME
    )

    if role is None:
        await interaction.response.send_message(
            f"❌ Couldn't find the `{ACCESS_ROLE_NAME}` role.",
            ephemeral=True
        )
        return

    try:
        await user.add_roles(
            role,
            reason="Temporary access granted"
        )

    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ I cannot manage that role. Check my Manage Roles "
            "permission and make sure my bot role is above "
            "Downgrade Access.",
            ephemeral=True
        )
        return

    key = f"{interaction.guild.id}:{user.id}"
    expires_at = time.time() + duration.value

    temp_access_expirations[key] = expires_at
    save_temp_access()

    old_task = temp_access_tasks.get(key)

    if old_task and not old_task.done():
        old_task.cancel()

    temp_access_tasks[key] = asyncio.create_task(
        remove_temp_role_later(
            interaction.guild.id,
            user.id,
            expires_at
        )
    )

    await interaction.response.send_message(
        f"✅ {user.mention} has received `Downgrade Access` "
        f"for **{duration.name}**.",
        ephemeral=True
    )


# ------------------------------
# BOT READY
# ------------------------------

@bot.event
async def on_ready():

    if GUILD_ID.isdigit():
        guild = discord.Object(id=int(GUILD_ID))
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)

        print(
            f"Logged in as {bot.user}; "
            f"commands synced to {GUILD_ID}"
        )

    else:
        await bot.tree.sync()

        print(
            f"Logged in as {bot.user}; "
            f"global commands synced"
        )

    # Restore temporary role timers after restart
    for key, expires_at in list(temp_access_expirations.items()):

        if key not in temp_access_tasks:
            guild_id, user_id = map(int, key.split(":"))

            temp_access_tasks[key] = asyncio.create_task(
                remove_temp_role_later(
                    guild_id,
                    user_id,
                    expires_at
                )
            )


# ------------------------------
# DOWNGRADE COMMAND
# ------------------------------

@bot.tree.command(
    name="downgrade",
    description="Downgrade an AEP project"
)
@discord.app_commands.describe(
    file="Your AEP project",
    target="Target version"
)
@discord.app_commands.choices(
    target=[
        discord.app_commands.Choice(name=v, value=v)
        for v in VERSIONS
    ]
)
async def downgrade(
    interaction: discord.Interaction,
    file: discord.Attachment,
    target: discord.app_commands.Choice[str]
):

    if not await check_conversion_access(interaction):
        return

    await handle_conversion(
        interaction,
        file,
        target.value,
        "aep"
    )


# ------------------------------
# FFX COMMAND
# ------------------------------

@bot.tree.command(
    name="ffx",
    description="Upgrade or downgrade an FFX preset"
)
@discord.app_commands.describe(
    file="Your FFX preset",
    direction="Choose upgrade or downgrade",
    target="Choose the destination After Effects version"
)
@discord.app_commands.choices(
    direction=[
        discord.app_commands.Choice(
            name="Upgrade",
            value="upgrade"
        ),
        discord.app_commands.Choice(
            name="Downgrade",
            value="downgrade"
        )
    ],
    target=[
        discord.app_commands.Choice(name=v, value=v)
        for v in FFX_VERSIONS
    ]
)
async def ffx(
    interaction: discord.Interaction,
    file: discord.Attachment,
    direction: discord.app_commands.Choice[str],
    target: discord.app_commands.Choice[str]
):

    if not await check_conversion_access(interaction):
        return

    await interaction.response.defer(
        ephemeral=True,
        thinking=True
    )

    if not file.filename.lower().endswith(".ffx"):
        await interaction.followup.send(
            "Please upload an .ffx file.",
            ephemeral=True
        )
        return

    if file.size > 20 * 1024 * 1024:
        await interaction.followup.send(
            "The file exceeds the 20 MB limit.",
            ephemeral=True
        )
        return

    os.makedirs("uploads", exist_ok=True)
    os.makedirs("outputs", exist_ok=True)

    safe_name = os.path.basename(file.filename)

    source = os.path.join(
        "uploads",
        f"{interaction.id}_{safe_name}"
    )

    output = os.path.join(
        "outputs",
        f"{interaction.id}_converted_{safe_name}"
    )

    try:
        await file.save(source)

        source_version, target_version, experimental = convert_ffx(
            source,
            output,
            target.value,
            direction.value
        )

        message = (
            f"**FFX conversion finished**\n"
            f"Direction: `{direction.value.title()}`\n"
            f"From: `{source_version}`\n"
            f"To: `{target_version}`"
        )

        if experimental:
            message += (
                "\n\n⚠️ **Experimental profile:** this version marker "
                "has not been verified. Compatibility is not guaranteed."
            )

        message += (
            "\n\nThis changes version metadata only. It does not "
            "translate effects, plugins, or preset internals. "
            "Test the result in After Effects."
        )

        await interaction.followup.send(
            content=message,
            file=discord.File(output),
            ephemeral=True
        )

    except ConversionError as exc:
        await interaction.followup.send(
            f"**Could not convert:** {exc}",
            ephemeral=True
        )

    except Exception as exc:
        await interaction.followup.send(
            f"Unexpected error: `{type(exc).__name__}`",
            ephemeral=True
        )

    finally:
        for path in (source, output):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass


# ------------------------------
# VERSIONS COMMAND
# ------------------------------

@bot.tree.command(
    name="versions",
    description="Show FFX conversion versions"
)
async def versions(interaction: discord.Interaction):

    await interaction.response.send_message(
        "**FFX targets:**\n"
        + "\n".join(FFX_VERSIONS)
        + "\n\nOlder profiles are experimental.",
        ephemeral=True
    )


# ------------------------------
# HELP COMMAND
# ------------------------------

@bot.tree.command(
    name="help",
    description="Show bot commands"
)
async def help_command(interaction: discord.Interaction):

    await interaction.response.send_message(
        "**Sampha's Downgrader**\n"
        "`/ffx` — upload an FFX, choose upgrade/downgrade and target.\n"
        "`/downgrade` — downgrade an AEP project.\n"
        "`/versions` — show FFX targets.\n"
        "`/activate` — activate conversion commands temporarily.\n"
        "`/deactivate` — deactivate conversion commands.\n"
        "`/tempaccess` — give a user temporary access.\n"
        "FFX conversion changes version metadata only.",
        ephemeral=True
    )


# ------------------------------
# START BOT
# ------------------------------

if __name__ == "__main__":

    if not TOKEN:
        raise SystemExit(
            "Missing DISCORD_TOKEN in .env"
        )

    load_temp_access()
    bot.run(TOKEN)
