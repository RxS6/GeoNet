import os
import aiosqlite
import discord
from discord.ext import commands
from datetime import datetime
from collections import defaultdict
from keep_alive import keep_alive

# =========================
# Database setup
# =========================
async def init_db():
    async with aiosqlite.connect('roles.db') as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS warnings (
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                warning TEXT NOT NULL,
                PRIMARY KEY (user_id, guild_id, warning)
            )
        ''')
        await conn.commit()

removed_roles = {}
log_channel_id = 1415343089974902987  # Your log channel

# =========================
# Logging
# =========================
async def log_command(ctx, description: str, color: discord.Color):
    log_channel = ctx.guild.get_channel(log_channel_id)
    if log_channel:
        embed = discord.Embed(
            title="Command Log",
            description=description,
            color=color,
            timestamp=datetime.utcnow()
        )
        embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)
        embed.set_footer(text=f"Used in #{ctx.channel.name}", icon_url=ctx.guild.icon.url)
        await log_channel.send(embed=embed)

# =========================
# DB Functions for Warnings
# =========================
async def add_warning(user_id, guild_id, warning):
    async with aiosqlite.connect('roles.db') as conn:
        await conn.execute(
            'INSERT OR IGNORE INTO warnings (user_id, guild_id, warning) VALUES (?, ?, ?)',
            (user_id, guild_id, warning)
        )
        await conn.commit()

async def remove_warning(user_id, guild_id, warning):
    async with aiosqlite.connect('roles.db') as conn:
        await conn.execute(
            'DELETE FROM warnings WHERE user_id = ? AND guild_id = ? AND warning = ?',
            (user_id, guild_id, warning)
        )
        await conn.commit()

async def check_warnings(user_id, guild_id):
    async with aiosqlite.connect('roles.db') as conn:
        async with conn.execute(
            'SELECT warning FROM warnings WHERE user_id = ? AND guild_id = ?',
            (user_id, guild_id)
        ) as cursor:
            warnings = [row[0] for row in await cursor.fetchall()]
    return warnings

# =========================
# Bot Setup
# =========================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='$', intents=intents)

@bot.event
async def on_ready():
    await init_db()
    print(f'✅ Logged in as {bot.user} ({bot.user.id})')

# =========================
# Staff Commands
# =========================

# Trial Command (2 roles)
@bot.command(name='trial')
@commands.has_permissions(manage_roles=True)
async def trial(ctx, member: discord.Member):
    role1_id = 1410667335119016070
    role2_id = 1410798804013289524
    role1 = ctx.guild.get_role(role1_id)
    role2 = ctx.guild.get_role(role2_id)

    if role1 and role2:
        await member.add_roles(role1, role2)
        await ctx.send(f"Assigned <@&{role1.id}> and <@&{role2.id}> to {member.mention}.")
        await log_command(ctx, f"**Assigned trial roles** to {member.mention}.", discord.Color.blue())
    else:
        await ctx.send("⚠️ Required roles not found.")

# Perm Demote Command (6 roles)
@bot.command(name='permdemote')
@commands.has_permissions(manage_roles=True)
async def permdemote(ctx, member: discord.Member):
    role_ids_to_remove = [
        1410667335119016070,
        1410685034884759582,
        1410667334246469715,
        1410667333105618954,
        1410667331901718639,
        1410667330467266707
    ]
    roles_to_remove = [ctx.guild.get_role(rid) for rid in role_ids_to_remove if ctx.guild.get_role(rid) in member.roles]

    if roles_to_remove:
        await member.remove_roles(*roles_to_remove)
        mentions = " ".join([f"<@&{r.id}>" for r in roles_to_remove])
        await ctx.send(f"Removed {mentions} from {member.mention}.")
        await log_command(ctx, f"**Permdemoted** {member.mention}. Roles removed: {mentions}", discord.Color.red())
    else:
        await ctx.send(f"{member.mention} has none of the target roles.")

# Rape / Recover
@bot.command()
@commands.has_permissions(manage_roles=True)
async def rape(ctx, user: discord.Member):
    roles = user.roles[1:]  # exclude @everyone
    if not roles:
        await ctx.send(f"{user.mention} has no roles to remove!")
        return
    removed_roles[user.id] = roles
    for role in roles:
        await user.remove_roles(role)
    await ctx.send(f"Raped all roles from {user.mention} and stored them for recovery.")

@bot.command()
@commands.has_permissions(manage_roles=True)
async def recover(ctx, user: discord.Member):
    if user.id not in removed_roles:
        await ctx.send(f"{user.mention} has no roles stored for recovery!")
        return
    for role in removed_roles[user.id]:
        await user.add_roles(role)
    removed_roles.pop(user.id)
    await ctx.send(f"Recovered all roles for {user.mention}.")

# =========================
# Warning System
# =========================
@bot.command(name='warn')
@commands.has_permissions(manage_roles=True)
async def warn(ctx, member: discord.Member, *, reason: str):
    await add_warning(member.id, ctx.guild.id, reason)
    await ctx.send(f"{member.mention} has been warned for: {reason}")
    await log_command(ctx, f"**Warned** {member.mention} for: {reason}", discord.Color.orange())

@bot.command(name='unwarn')
@commands.has_permissions(manage_roles=True)
async def unwarn(ctx, member: discord.Member, *, reason: str):
    await remove_warning(member.id, ctx.guild.id, reason)
    await ctx.send(f"Warning removed for {member.mention}: {reason}")
    await log_command(ctx, f"**Unwarned** {member.mention}. Reason: {reason}", discord.Color.green())

@bot.command(name='warnings')
@commands.has_permissions(manage_roles=True)
async def warnings(ctx, member: discord.Member):
    warnings_list = await check_warnings(member.id, ctx.guild.id)
    if warnings_list:
        embed = discord.Embed(title=f"Warnings for {member.name}", color=discord.Color.orange(), timestamp=datetime.utcnow())
        for i, warning in enumerate(warnings_list, 1):
            embed.add_field(name=f"Warning {i}", value=warning, inline=False)
        await ctx.send(embed=embed)
    else:
        await ctx.send(f"{member.mention} has no warnings.")

# =========================
# New Commands You Wanted
# =========================

# Kick
@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    await member.kick(reason=reason)
    await ctx.send(f"Kicked {member.mention} for: {reason}")
    await log_command(ctx, f"**Kicked** {member.mention} for: {reason}", discord.Color.red())

# Clear / Purge
@bot.command(name="clear")
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int):
    await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"🧹 Cleared {amount} messages.", delete_after=5)

# Lock / Unlock channel
@bot.command()
@commands.has_permissions(manage_channels=True)
async def lock(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False)
    await ctx.send("🔒 Channel locked.")

@bot.command()
@commands.has_permissions(manage_channels=True)
async def unlock(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=True)
    await ctx.send("🔓 Channel unlocked.")

# Role Management
@bot.command()
@commands.has_permissions(manage_roles=True)
async def addrole(ctx, member: discord.Member, role: discord.Role):
    await member.add_roles(role)
    await ctx.send(f"Added <@&{role.id}> to {member.mention}.")

@bot.command()
@commands.has_permissions(manage_roles=True)
async def removerole(ctx, member: discord.Member, role: discord.Role):
    await member.remove_roles(role)
    await ctx.send(f"Removed <@&{role.id}> from {member.mention}.")

# Info Commands
@bot.command()
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author
    roles = " ".join([f"<@&{r.id}>" for r in member.roles if r != ctx.guild.default_role]) or "None"
    embed = discord.Embed(title=f"User Info - {member}", color=discord.Color.blue(), timestamp=datetime.utcnow())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="ID", value=member.id, inline=False)
    embed.add_field(name="Joined Server", value=member.joined_at.strftime("%Y-%m-%d %H:%M:%S"), inline=False)
    embed.add_field(name="Account Created", value=member.created_at.strftime("%Y-%m-%d %H:%M:%S"), inline=False)
    embed.add_field(name="Roles", value=roles, inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def serverinfo(ctx):
    guild = ctx.guild
    embed = discord.Embed(title=f"Server Info - {guild.name}", color=discord.Color.green(), timestamp=datetime.utcnow())
    embed.set_thumbnail(url=guild.icon.url if guild.icon else discord.Embed.Empty)
    embed.add_field(name="ID", value=guild.id, inline=False)
    embed.add_field(name="Owner", value=guild.owner.mention, inline=False)
    embed.add_field(name="Members", value=guild.member_count, inline=False)
    embed.add_field(name="Created On", value=guild.created_at.strftime("%Y-%m-%d %H:%M:%S"), inline=False)
    await ctx.send(embed=embed)

# =========================
# Run Bot
# =========================
keep_alive()
bot.run(os.getenv('DISCORD_TOKEN'))
