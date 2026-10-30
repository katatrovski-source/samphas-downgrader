
import os
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


async def handle_conversion(interaction, attachment, target, kind):
    await interaction.response.defer(ephemeral=True, thinking=True)

    suffix = ".aep" if kind == "aep" else ".ffx"

    if not attachment.filename.lower().endswith(suffix):
        await interaction.followup.send(
            f"Please upload a `{suffix}` file.", ephemeral=True
        )
        return

    if attachment.size > 20 * 1024 * 1024:
        await interaction.followup.send(
            "The file exceeds the 20 MB limit.", ephemeral=True
        )
        return

    os.makedirs("uploads", exist_ok=True)
    os.makedirs("outputs", exist_ok=True)

    safe_name = os.path.basename(attachment.filename)
    source_path = os.path.join("uploads", f"{interaction.id}_{safe_name}")
    output_path = os.path.join(
        "outputs",
        f"{interaction.id}_{os.path.splitext(safe_name)[0]}_converted{suffix}",
    )

    try:
        await attachment.save(source_path)

        warning = ""

        if kind == "aep":
            source_version = detect_aep_version(source_path)
            downgrade_aep(source_path, output_path, target)
            result = f"**AEP conversion:** {source_version} → {target}"

        else:
            raise ConversionError(
                "Use the /ffx command for FFX files."
            )

        await interaction.followup.send(
            content=result + warning,
            file=discord.File(output_path),
            ephemeral=True,
        )

    except ConversionError as exc:
        await interaction.followup.send(
            f"**Could not convert:** {exc}", ephemeral=True
        )
    except Exception as exc:
        await interaction.followup.send(
            f"Unexpected error: `{type(exc).__name__}`",
            ephemeral=True,
        )
    finally:
        for path in (source_path, output_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass


@bot.event
async def on_ready():
    if GUILD_ID.isdigit():
        guild = discord.Object(id=int(GUILD_ID))
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        print(f"Logged in as {bot.user}; commands synced to {GUILD_ID}")
    else:
        await bot.tree.sync()
        print(f"Logged in as {bot.user}; global commands synced")


@bot.tree.command(name="downgrade", description="Downgrade an AEP project")
@discord.app_commands.describe(file="Your AEP project", target="Target version")
@discord.app_commands.choices(
    target=[discord.app_commands.Choice(name=v, value=v) for v in VERSIONS]
)
async def downgrade(interaction, file: discord.Attachment, target: discord.app_commands.Choice[str]):
    await handle_conversion(interaction, file, target.value, "aep")


@bot.tree.command(name="ffx", description="Upgrade or downgrade an FFX preset")
@discord.app_commands.describe(
    file="Your FFX preset",
    direction="Choose upgrade or downgrade",
    target="Choose the destination After Effects version",
)
@discord.app_commands.choices(
    direction=[
        discord.app_commands.Choice(name="Upgrade", value="upgrade"),
        discord.app_commands.Choice(name="Downgrade", value="downgrade"),
    ],
    target=[
        discord.app_commands.Choice(name=v, value=v)
        for v in FFX_VERSIONS
    ],
)
async def ffx(
    interaction: discord.Interaction,
    file: discord.Attachment,
    direction: discord.app_commands.Choice[str],
    target: discord.app_commands.Choice[str],
):
    await interaction.response.defer(ephemeral=True, thinking=True)

    if not file.filename.lower().endswith(".ffx"):
        await interaction.followup.send(
            "Please upload an .ffx file.", ephemeral=True
        )
        return

    if file.size > 20 * 1024 * 1024:
        await interaction.followup.send(
            "The file exceeds the 20 MB limit.", ephemeral=True
        )
        return

    os.makedirs("uploads", exist_ok=True)
    os.makedirs("outputs", exist_ok=True)

    safe_name = os.path.basename(file.filename)
    source = os.path.join("uploads", f"{interaction.id}_{safe_name}")
    output = os.path.join(
        "outputs", f"{interaction.id}_converted_{safe_name}"
    )

    try:
        await file.save(source)

        source_version, target_version, experimental = convert_ffx(
            source,
            output,
            target.value,
            direction.value,
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
            ephemeral=True,
        )

    except ConversionError as exc:
        await interaction.followup.send(
            f"**Could not convert:** {exc}", ephemeral=True
        )
    except Exception as exc:
        await interaction.followup.send(
            f"Unexpected error: `{type(exc).__name__}`",
            ephemeral=True,
        )
    finally:
        for path in (source, output):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass


@bot.tree.command(name="versions", description="Show FFX conversion versions")
async def versions(interaction: discord.Interaction):
    await interaction.response.send_message(
        "**FFX targets:**\n" + "\n".join(FFX_VERSIONS)
        + "\n\nOlder profiles are experimental.",
        ephemeral=True,
    )


@bot.tree.command(name="help", description="Show bot commands")
async def help_command(interaction: discord.Interaction):
    await interaction.response.send_message(
        "**Sampha's Downgrader**\n"
        "`/ffx` — upload an FFX, choose upgrade/downgrade and target version.\n"
        "`/downgrade` — downgrade an AEP project.\n"
        "`/versions` — show FFX targets.\n"
        "FFX conversion changes version metadata only.",
        ephemeral=True,
    )


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Missing DISCORD_TOKEN in .env")
    bot.run(TOKEN)
