import os
import re
import discord
from discord.ext import commands

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="*", intents=intents)


MUTE_REASONS = {
    "threat",
    "threats",
    "harassment",
    "harrasment",
    "hate speech",
    "nsfw",
    "advertising",
    "advertisement",
    "adv",
    "spam",
}


def get_reason(title):
    if "-" in title:
        return title.split("-", 1)[0].strip().lower()

    return "other"


def get_user_id(title):
    match = re.search(r"\b\d{17,20}\b", title)

    if match:
        return match.group(0)

    return None


@bot.event
async def on_ready():
    print(f"ANX bot is online as {bot.user}")


@bot.command()
async def bl(ctx):

    if not isinstance(ctx.channel, discord.Thread):
        await ctx.send(
            "❌ Use `*bl` inside a ban-proof forum post/thread."
        )
        return

    forum = ctx.channel.parent

    if not isinstance(forum, discord.ForumChannel):
        await ctx.send(
            "❌ This command must be used in a forum."
        )
        return

    # Stop duplicate Ban Logs in the same forum post
    async for message in ctx.channel.history(limit=50):
        if message.author == bot.user and message.embeds:
            if message.embeds[0].title == "Ban Log":
                return

    current_user_id = get_user_id(ctx.channel.name)

    if not current_user_id:
        await ctx.send(
            "❌ I couldn't find a Discord user ID in this forum post title."
        )
        return

    reason = get_reason(ctx.channel.name)

    # Count actual bans that happened BEFORE this forum post
    ban_count = 0

    try:
        async for entry in ctx.guild.audit_logs(
            limit=None,
            action=discord.AuditLogAction.ban
        ):
            if entry.target:
                if str(entry.target.id) == current_user_id:

                    if entry.created_at < ctx.channel.created_at:
                        ban_count += 1

    except discord.Forbidden:
        await ctx.send(
            "❌ ANX Bot needs the **View Audit Log** permission."
        )
        return

    except Exception as e:
        print(f"Audit log error: {e}")
        await ctx.send(
            "❌ I couldn't read the server audit log."
        )
        return

    # Create suggestion from the forum title
    if reason in MUTE_REASONS:
        suggestion = f"*mute {current_user_id} {reason}"

    elif reason == "doxxing" or reason == "doxing":
        suggestion = f"*ban {current_user_id} perm doxxing"

    else:
        suggestion = f"*ban {current_user_id} perm {reason}"

    embed = discord.Embed(
        title="Ban Log",
        description=f"**User ID:** `{current_user_id}`",
    )

    embed.add_field(
        name="Previous Bans",
        value=f"**{ban_count}**",
        inline=False
    )

    embed.add_field(
        name="Ban Suggestion",
        value=f"`{suggestion}`",
        inline=False
    )

    embed.set_footer(
        text="Suggestion only — ANX bot will not ban or mute anyone."
    )

    await ctx.send(embed=embed)


bot.run(TOKEN)