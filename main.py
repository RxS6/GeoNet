import discord
from discord.ext import commands
import sqlite3
import os
from datetime import datetime

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="$", intents=intents)
bot.remove_command("help")

# ===============================
# Database setup
# ===============================
conn = sqlite3.connect('warnings.db')
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS warnings
             (user_id INTEGER, guild_id INTEGER, reason TEXT)''')
conn.commit()

async def add_warning(user_id, guild_id, reason):
    c.execute("INSERT INTO warnings VALUES (?, ?, ?)", (user_id, guild_id, reason))
    conn.commit()

async def remove_warning(user_id, guild_id, reason):
    c.execute("DELETE FROM warnings WHERE user_id = ? AND guild_id = ? AND reason = ?",
              (user_id, guild_id, reason))
    conn.commit()

async def check_warnings(user_id, guild_id):
    c.execute("SELECT reason FROM warnings WHERE user_id = ? AND guild_id = ?",
              (user_id, guild_id))
    return [row[0] for row in c.fetchall()]

# ===============================
# Logging helper
# ===============================
async def log_command(ctx, description, color=discord.Color.blue()):
    log_channel_id = 1415343089974902987
    log_channel = ctx.guild.get_channel(log_channel_id)
    if log_channel:
        embed = discord.Embed(
            description=description,
            color=color,
            timestamp=datetime.utcnow()
        )
        embed.set_author(name=ctx.author, icon_url=ctx.author.avatar.url if ctx.author.avatar else discord.Embed.Empty)
        await log_channel.send(embed=embed)

# ===============================
# Trial Command
# ===============================
@bot.command(name='trial')
@commands.has_permissions(manage_roles=True)
async def trial(ctx, member: discord.Member):
    role1_id = 1410667335119016070
    role2_id = 1410798804013289524

    role1 = ctx.guild.get_role(role1_id)
    role2 = ctx.guild.get_role(role2_id)

    if role1 and role2:
        await member.add_roles(role1, role2)
        await ctx.send(f"Assigned {role1.name} and {role2.name} to {member.mention}.")
        description = f"**Assigned staff roles** to {member.mention}."
        await log_command(ctx, description, discord.Color.blue())

# ===============================
# Permanent Demote Command
# ===============================
@bot.command(name='permdemote')
@commands.has_permissions(manage_roles=True)
async def permdemote(ctx, member: discord.Member):
    roles_to_remove_ids = [
        1410667335119016070,
        1410685034884759582,
        1410667334246469715,
        1410667333105618954,
        1410667331901718639,
        1410667330467266707
    ]
    roles_to_remove = [ctx.guild.get_role(rid) for rid in roles_to_remove_ids if ctx.guild.get_role(rid) in member.roles]

    if roles_to_remove:
        await member.remove_roles(*roles_to_remove)
        await ctx.send(f"Removed targeted roles from {member.mention}.")
        description = f"**Demoted** {member.mention} (removed roles)."
        await log_command(ctx, description, discord.Color.red())
    else:
        await ctx.send(f"{member.mention} does not have any of the targeted roles.")

# ===============================
# Rape & Recover Commands
# ===============================
removed_roles = {}

@bot.command()
@commands.has_permissions(manage_roles=True)
async def rape(ctx, user: discord.Member):
    roles = user.roles[1:]  # skip @everyone
    if not roles:
        await ctx.send(f"{user.mention} has no roles to remove!")
        return
    removed_roles[user.id] = roles
    await user.remove_roles(*roles)
    await ctx.send(f"Removed all roles from {user.mention}.")
    await log_command(ctx, f"**Removed all roles** from {user.mention}", discord.Color.red())

@bot.command()
@commands.has_permissions(manage_roles=True)
async def recover(ctx, user: discord.Member):
    if user.id not in removed_roles:
        await ctx.send(f"No roles stored for {user.mention}. Use `rape` before recover.")
        return
    await user.add_roles(*removed_roles[user.id])
    await ctx.send(f"Restored roles to {user.mention}.")
    await log_command(ctx, f"**Restored roles** to {user.mention}", discord.Color.green())
    del removed_roles[user.id]

# ===============================
# Warn System
# ===============================
@bot.command(name='warn')
@commands.has_permissions(manage_roles=True)
async def warn(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    await add_warning(member.id, ctx.guild.id, reason)
    await ctx.send(f"{member.mention} has been warned for: {reason}")
    await log_command(ctx, f"**Warned** {member.mention} for: {reason}", discord.Color.orange())

@bot.command(name='unwarn')
@commands.has_permissions(manage_roles=True)
async def unwarn(ctx, member: discord.Member, *, reason: str = None):
    if not reason:
        await ctx.send("❌ Please provide the same reason used when warning.")
        return
    await remove_warning(member.id, ctx.guild.id, reason)
    await ctx.send(f"Warning removed for {member.mention}: {reason}")
    await log_command(ctx, f"**Unwarned** {member.mention}. Reason: {reason}", discord.Color.green())

@bot.command(name='warnings')
@commands.has_permissions(manage_roles=True)
async def warnings(ctx, member: discord.Member):
    warnings_list = await check_warnings(member.id, ctx.guild.id)
    if warnings_list:
        embed = discord.Embed(
            title=f"Warnings for {member.name}",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow()
        )
        if member.avatar:
            embed.set_thumbnail(url=member.avatar.url)
        for i, warning in enumerate(warnings_list, 1):
            embed.add_field(name=f"Warning {i}", value=warning, inline=False)
        await ctx.send(embed=embed)
    else:
        await ctx.send(f"{member.mention} has no warnings.")
    await log_command(ctx, f"**Checked warnings** for {member.mention}", discord.Color.blue())

# ===============================
# Ban / Unban Commands
# ===============================
@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="No reason provided"):
    await member.ban(reason=reason)
    await ctx.send(f"{member.mention} has been banned. Reason: {reason}")
    await log_command(ctx, f"**Banned** {member.mention} for: {reason}", discord.Color.red())

@bot.command(name="unban")
@commands.has_permissions(ban_members=True)
async def unban(ctx, *, member_name):
    banned_users = await ctx.guild.bans()
    for ban_entry in banned_users:
        user = ban_entry.user
        if user.name == member_name:
            await ctx.guild.unban(user)
            await ctx.send(f"Unbanned {user.mention}")
            await log_command(ctx, f"**Unbanned** {user.mention}", discord.Color.green())
            return
    await ctx.send(f"User {member_name} not found in banned list.")

# ===============================
# Custom Help Command
# ===============================
@bot.command(name="help")
async def help_command(ctx):
    embed = discord.Embed(
        title="📖 Bot Commands",
        description="Here are the available commands:",
        color=discord.Color.purple()
    )
    embed.add_field(name="$trial @user", value="Assigns trial roles.", inline=False)
    embed.add_field(name="$permdemote @user", value="Removes staff roles (demotion).", inline=False)
    embed.add_field(name="$rape @user", value="Removes all roles from a user.", inline=False)
    embed.add_field(name="$recover @user", value="Restores roles removed with `rape`.", inline=False)
    embed.add_field(name="$warn @user [reason]", value="Warn a user.", inline=False)
    embed.add_field(name="$unwarn @user [reason]", value="Remove a warning.", inline=False)
    embed.add_field(name="$warnings @user", value="Show all warnings of a user.", inline=False)
    embed.add_field(name="$ban @user [reason]", value="Ban a user.", inline=False)
    embed.add_field(name="$unban username", value="Unban a user by name.", inline=False)
    await ctx.send(embed=embed)

# ===============================
# Error Handler
# ===============================
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing argument: `{error.param.name}`. Use `$help` for command usage.")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don’t have permission to use this command.")
    elif isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Command not found. Use `$help` to see available commands.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Invalid argument. Please check and try again.")
    else:
        await ctx.send("⚠️ An unexpected error occurred. Please try again later.")
        raise error

# ===============================
# Run Bot
# ===============================
def keep_alive():
    from flask import Flask
    from threading import Thread
    app = Flask('')

    @app.route('/')
    def home():
        return "Bot is alive!"

    def run():
        app.run(host='0.0.0.0', port=8080)

    t = Thread(target=run)
    t.start()

keep_alive()
bot.run(os.getenv("DISCORD_TOKEN"))
