import os
import sqlite3
import re
import asyncio
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands


# ============================================================
# CONFIG
# ============================================================

TOKEN = os.getenv("DISCORD_TOKEN")

DATABASE_FILE = "anx_bans.db"


# ============================================================
# BOT SETUP
# ============================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="*",
    intents=intents
)


# ============================================================
# DATABASE
# ============================================================

db = sqlite3.connect(
    DATABASE_FILE,
    check_same_thread=False
)

cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS temporary_bans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    banned_at TEXT NOT NULL,
    unban_at TEXT NOT NULL,
    duration TEXT NOT NULL,
    moderator_id INTEGER NOT NULL
)
""")

db.commit()


# ============================================================
# BAN DURATIONS
# ============================================================

def get_ban_duration(previous_bans):
    if previous_bans <= 0:
        return "3d"
    if previous_bans == 1:
        return "7d"
    if previous_bans == 2:
        return "10d"
    return "20d"


def duration_to_timedelta(duration):

    days = int(duration[:-1])

    return timedelta(days=days)


# ============================================================
# USER ID FROM THREAD TITLE
# ============================================================

def get_user_id(title):

    match = re.search(
        r"\b\d{17,20}\b",
        title
    )

    if match:
        return int(match.group(0))

    return None


# ============================================================
# REASON FROM THREAD TITLE
# ============================================================

def get_reason(title, user_id):

    title = title.replace(
        str(user_id),
        ""
    )

    title = title.strip()

    title = title.strip(
        "-|:"
    )

    if not title:
        return "other"

    return title.lower()


# ============================================================
# BAN STATISTICS
# ============================================================

async def get_ban_stats(
    guild,
    user_id,
    thread_created_at
):

    now = discord.utils.utcnow()

    month_ago = now - timedelta(days=30)
    three_months_ago = now - timedelta(days=90)
    year_ago = now - timedelta(days=365)

    all_time = 0
    month = 0
    three_months = 0
    year = 0

    most_recent = None

    async for entry in guild.audit_logs(
        limit=None,
        action=discord.AuditLogAction.ban
    ):

        if entry.target is None:
            continue

        if entry.target.id != user_id:
            continue

        if entry.created_at >= thread_created_at:
            continue

        all_time += 1

        if most_recent is None:
            most_recent = entry.created_at

        if entry.created_at >= month_ago:
            month += 1

        if entry.created_at >= three_months_ago:
            three_months += 1

        if entry.created_at >= year_ago:
            year += 1

    return {
        "all_time": all_time,
        "month": month,
        "three_months": three_months,
        "year": year,
        "most_recent": most_recent
    }


# ============================================================
# PERMISSION CHECK
# ============================================================

def can_moderate(member):

    if member.guild_permissions.administrator:
        return True

    if member.guild_permissions.ban_members:
        return True

    return False


# ============================================================
# BAN DECISION BUTTONS
# ============================================================

class BanDecisionView(discord.ui.View):

    def __init__(
        self,
        user_id,
        duration
    ):

        super().__init__(
            timeout=None
        )

        self.user_id = user_id
        self.duration = duration
        self.decided = False

    async def disable_buttons(
        self,
        interaction
    ):

        for item in self.children:
            item.disabled = True

        await interaction.message.edit(
            view=self
        )

    @discord.ui.button(
        label="Ban",
        emoji="🔨",
        style=discord.ButtonStyle.danger,
        custom_id="anx_ban"
    )
    async def ban_button(
        self,
        interaction,
        button
    ):

        if self.decided:

            await interaction.response.send_message(
                "❌ A decision has already been made.",
                ephemeral=True
            )

            return

        if not can_moderate(interaction.user):

            await interaction.response.send_message(
                "❌ You don't have permission to approve bans.",
                ephemeral=True
            )

            return

        if not interaction.guild.me.guild_permissions.ban_members:

            await interaction.response.send_message(
                "❌ I don't have the **Ban Members** permission.",
                ephemeral=True
            )

            return

        self.decided = True

        await interaction.response.defer()

        try:

            user = await bot.fetch_user(
                self.user_id
            )

            now = datetime.now(
                timezone.utc
            )

            unban_at = (
                now +
                duration_to_timedelta(
                    self.duration
                )
            )

            await interaction.guild.ban(
                user,
                reason=(
                    f"ANX Ban Log approved by "
                    f"{interaction.user} "
                    f"({interaction.user.id})"
                )
            )

            cursor.execute(
                """
                INSERT INTO temporary_bans
                (
                    guild_id,
                    user_id,
                    banned_at,
                    unban_at,
                    duration,
                    moderator_id
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    interaction.guild.id,
                    self.user_id,
                    now.isoformat(),
                    unban_at.isoformat(),
                    self.duration,
                    interaction.user.id
                )
            )

            db.commit()

            for item in self.children:
                item.disabled = True

            embed = interaction.message.embeds[0]

            embed.add_field(
                name="Decision:",
                value=(
                    f"🔨 **Ban approved** by "
                    f"{interaction.user.mention}"
                ),
                inline=False
            )

            await interaction.message.edit(
                embed=embed,
                view=self
            )

            asyncio.create_task(
                wait_for_unban(
                    interaction.guild.id,
                    self.user_id,
                    unban_at
                )
            )

        except discord.Forbidden:

            self.decided = False

            await interaction.followup.send(
                "❌ Discord denied the ban. "
                "Check my role position and permissions.",
                ephemeral=True
            )

        except discord.NotFound:

            self.decided = False

            await interaction.followup.send(
                "❌ I couldn't find that user.",
                ephemeral=True
            )

        except Exception as error:

            self.decided = False

            print(
                f"Ban error: {error}"
            )

            await interaction.followup.send(
                "❌ Something went wrong while banning the user.",
                ephemeral=True
            )

    @discord.ui.button(
        label="Reject",
        emoji="❌",
        style=discord.ButtonStyle.secondary,
        custom_id="anx_reject"
    )
    async def reject_button(
        self,
        interaction,
        button
    ):

        if self.decided:

            await interaction.response.send_message(
                "❌ A decision has already been made.",
                ephemeral=True
            )

            return

        if not can_moderate(interaction.user):

            await interaction.response.send_message(
                "❌ You don't have permission to reject this recommendation.",
                ephemeral=True
            )

            return

        self.decided = True

        for item in self.children:
            item.disabled = True

        embed = interaction.message.embeds[0]

        embed.add_field(
            name="Decision:",
            value=(
                f"❌ **Recommendation rejected** by "
                f"{interaction.user.mention}"
            ),
            inline=False
        )

        await interaction.response.edit_message(
            embed=embed,
            view=self
        )


# ============================================================
# AUTOMATIC UNBAN
# ============================================================

async def wait_for_unban(
    guild_id,
    user_id,
    unban_at
):

    try:

        now = datetime.now(
            timezone.utc
        )

        seconds = (
            unban_at - now
        ).total_seconds()

        if seconds > 0:
            await asyncio.sleep(
                seconds
            )

        guild = bot.get_guild(
            guild_id
        )

        if guild is None:
            return

        try:

            user = await bot.fetch_user(
                user_id
            )

            await guild.unban(
                user,
                reason="ANX temporary ban expired"
            )

            cursor.execute(
                """
                DELETE FROM temporary_bans
                WHERE guild_id = ?
                AND user_id = ?
                """,
                (
                    guild_id,
                    user_id
                )
            )

            db.commit()

            print(
                f"Automatically unbanned {user_id}"
            )

        except discord.NotFound:
            pass

        except discord.Forbidden:
            print(
                f"Could not unban {user_id}: "
                "missing permission."
            )

    except Exception as error:

        print(
            f"Unban error: {error}"
        )


# ============================================================
# RELOAD BANS AFTER RESTART
# ============================================================

async def reload_temporary_bans():

    cursor.execute(
        """
        SELECT
            guild_id,
            user_id,
            unban_at
        FROM temporary_bans
        """
    )

    rows = cursor.fetchall()

    for guild_id, user_id, unban_at in rows:

        try:

            unban_time = datetime.fromisoformat(
                unban_at
            )

            asyncio.create_task(
                wait_for_unban(
                    guild_id,
                    user_id,
                    unban_time
                )
            )

        except Exception as error:

            print(
                f"Could not reload ban: {error}"
            )


# ============================================================
# BOT READY
# ============================================================

@bot.event
async def on_ready():

    print(
        f"ANX Bot is online as {bot.user}"
    )

    await reload_temporary_bans()

    print(
        "Temporary bans loaded."
    )


# ============================================================
# *BL COMMAND
# ============================================================

@bot.command(
    name="bl"
)
async def bl(ctx):

    if not isinstance(
        ctx.channel,
        discord.Thread
    ):

        await ctx.send(
            "❌ Use `*bl` inside a ban-log thread."
        )

        return

    user_id = get_user_id(
        ctx.channel.name
    )

    if user_id is None:

        await ctx.send(
            "❌ I couldn't find a Discord user ID "
            "in the thread title."
        )

        return

    reason = get_reason(
        ctx.channel.name,
        user_id
    )

    try:

        stats = await get_ban_stats(
            ctx.guild,
            user_id,
            ctx.channel.created_at
        )

    except discord.Forbidden:

        await ctx.send(
            "❌ I need the **View Audit Log** permission."
        )

        return

    # --------------------------------------------------------
    # RECOMMENDED DURATION
    # --------------------------------------------------------

    duration = get_ban_duration(
        stats["all_time"]
    )

    recommendation = (
        f"/ban {user_id} {duration} {reason}"
    )
    recommendation_lines = [
        f"/ban user:{user_id} duration:{duration}",
        f"reason:{reason}",
        "If you believe you were falsely banned,",
        "you may use the [ban appeal server]",
        "(https://discord.gg/WhcZwpBwPF)",
    ]

    # --------------------------------------------------------
    # EMBED
    # --------------------------------------------------------

    embed = discord.Embed(
        title=(
            f"Ban Logs for "
            f"<@{user_id}> "
            f"({user_id})"
        ),
        color=discord.Color.red()
    )
    embed = discord.Embed(
        description=f"Ban Logs for <@{user_id}> ({user_id}):",
        color=discord.Color.red()
    )

    embed.add_field(
        name="Number of bans (all time):",
        value=str(
            stats["all_time"]
        ),
        inline=True
    )

    if stats["most_recent"]:

        recent = discord.utils.format_dt(
            stats["most_recent"],
            style="F"
        )

    else:

        recent = "N/A"

    embed.add_field(
        name="Most recent ban:",
        value=recent,
        inline=True
    )

    embed.add_field(
        name="Number of bans (past month):",
        value=str(stats["month"]) if stats["month"] else "N/A",
        inline=False
    )

    embed.add_field(
        name="Number of bans (past 3 months):",
        value=str(stats["three_months"]) if stats["three_months"] else "N/A",
        inline=True
    )

    embed.add_field(
        name="Number of bans (past year):",
        value=str(stats["year"]) if stats["year"] else "N/A",
        inline=True
    )

    embed.add_field(
        name="Ban Recommendation:",
        value=(
            f"```"
            f"{recommendation}"
            f"```"
        ),
        inline=False
    )
    embed.add_field(
        name="Ban Recommendation:",
        value="\n".join(f"`{line}`" for line in recommendation_lines),
        inline=False
    )

    embed.timestamp = discord.utils.utcnow()

    embed.set_footer(
        text=f"Requested by {ctx.author}"
    )

    embed.timestamp = discord.utils.utcnow()

    # --------------------------------------------------------
    # BUTTONS
    # --------------------------------------------------------

    view = BanDecisionView(
        user_id,
        duration
    )

    await ctx.send(
        embed=embed,
        view=view
    )


# ============================================================
# START
# ============================================================

if not TOKEN:

    raise RuntimeError(
        "DISCORD_TOKEN is not set."
    )


bot.run(TOKEN)
