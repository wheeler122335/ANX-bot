import os
import re
from datetime import timedelta

import discord
from discord.ext import commands


TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="*", intents=intents)


def get_user_id(thread_title):
    match = re.search(r"\b\d{17,20}\b", thread_title)
    return int(match.group(0)) if match else None


def get_reason(thread_title, user_id):
    reason = thread_title.replace(str(user_id), "").strip().strip(" -|:")
    return reason.lower() if reason else "other"


def get_ban_duration(previous_bans):
    if previous_bans <= 0:
        return "3d"
    if previous_bans == 1:
        return "7d"
    if previous_bans == 2:
        return "10d"
    return "20d"


async def get_ban_stats(guild, user_id, thread_created_at):
    now = discord.utils.utcnow()
    month_ago = now - timedelta(days=30)
    three_months_ago = now - timedelta(days=90)
    year_ago = now - timedelta(days=365)

    stats = {
        "all_time": 0,
        "month": 0,
        "three_months": 0,
        "year": 0,
        "most_recent": None,
    }

    async for entry in guild.audit_logs(
        limit=None,
        action=discord.AuditLogAction.ban,
    ):
        if entry.target is None or entry.target.id != user_id:
            continue
        if entry.created_at >= thread_created_at:
            continue

        stats["all_time"] += 1
        if stats["most_recent"] is None:
            stats["most_recent"] = entry.created_at
        if entry.created_at >= month_ago:
            stats["month"] += 1
        if entry.created_at >= three_months_ago:
            stats["three_months"] += 1
        if entry.created_at >= year_ago:
            stats["year"] += 1

    return stats


@bot.event
async def on_ready():
    print(f"ANX bot is online as {bot.user}")


@bot.command(name="bl")
async def bl(ctx):
    if ctx.guild is None or not isinstance(ctx.channel, discord.Thread):
        await ctx.send("Use `*bl` inside a ban-log thread.")
        return

    user_id = get_user_id(ctx.channel.name)
    if user_id is None:
        await ctx.send("I couldn't find a Discord user ID in the thread title.")
        return

    reason = get_reason(ctx.channel.name, user_id)

    try:
        stats = await get_ban_stats(ctx.guild, user_id, ctx.channel.created_at)
    except discord.Forbidden:
        await ctx.send("I need the **View Audit Log** permission.")
        return

    duration = get_ban_duration(stats["all_time"])
    recommendation = (
        f"/ban user:{user_id} duration:{duration}\n"
        f"reason:{reason}"
    )

    embed = discord.Embed(
        description=f"Ban Logs for <@{user_id}> ({user_id}):",
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow(),
    )

    embed.add_field(
        name="Number of bans (all time):",
        value=str(stats["all_time"]),
        inline=True,
    )

    recent = (
        discord.utils.format_dt(stats["most_recent"], style="F")
        if stats["most_recent"]
        else "N/A"
    )
    embed.add_field(
        name="Most recent ban:",
        value=recent,
        inline=True,
    )

    embed.add_field(
        name="Number of bans (past month):",
        value=str(stats["month"]) if stats["month"] else "N/A",
        inline=False,
    )

    embed.add_field(
        name="Number of bans (past 3 months):",
        value=str(stats["three_months"]) if stats["three_months"] else "N/A",
        inline=True,
    )

    embed.add_field(
        name="Number of bans (past year):",
        value=str(stats["year"]) if stats["year"] else "N/A",
        inline=True,
    )

    embed.add_field(
        name="\u200b",
        value=f"```\n{recommendation}\n```",
        inline=False,
    )

    await ctx.send(embed=embed)


if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set.")

bot.run(TOKEN)
