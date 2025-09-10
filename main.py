import os
import aiosqlite
import discord
from discord.ext import commands
from datetime import datetime
from collections import defaultdict
from keep_alive import keep_alive

# Database setup
async def init_db():
    async with aiosqlite.connect('roles.db') as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS roles (
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                PRIMARY KEY (user_id, guild_id, role_id)
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS warnings (
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                warning TEXT NOT NULL,
                PRIMARY KEY (user_id, guild_id, warning)
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS removed_roles (
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                PRIMARY KEY (user_id, guild_id, role_id)
            )
        ''')
        await conn.commit()

removed_roles = {}
log_channel_id = 1415343089974902987

# Logging function
async def log_command(ctx, description: str, color: discord.Color):
    log_channel = ctx.guild.get_channel(log_channel_id)
    if log_channel:
        embed = discord.Embed(
            title="Command Log",
            description=description,
            color=color,
            timestamp=datetime.utcnow()
        )
        embed.set_author(name=ctx.author.name, icon_url=ctx.author.avatar.url)
        embed.set_footer(text=f"Used in #{ctx.channel.name}", icon_url=ctx.guild.icon.url)
        await log_channel.send(embed=embed)

# Database functions
async def store_roles(user_id, guild_id, role_ids):
    async with aiosqlite.connect('roles.db') as conn:
        await conn.executemany('''
            INSERT OR IGNORE INTO roles (user_id, guild_id, role_id)
            VALUES (?, ?, ?)
        ''', [(user_id, guild_id, role_id) for role_id in role_ids])
        await conn.commit()

async def get_roles(user_id, guild_id):
    async with aiosqlite.connect('roles.db') as conn:
        async with conn.execute('SELECT role_id FROM roles WHERE user_id = ? AND guild_id = ?', (user_id, guild_id)) as cursor:
            roles = [row[0] for row in await cursor.fetchall()]
    return roles

async def remove_roles(user_id, guild_id):
    async with aiosqlite.connect('roles.db') as conn:
        await conn.execute('DELETE FROM roles WHERE user_id = ? AND guild_id = ?', (user_id, guild_id))
        await conn.commit()

async def add_warning(user_id, guild_id, warning):
    async with aiosqlite.connect('roles.db') as conn:
        await conn.execute('INSERT OR IGNORE INTO warnings (user_id, guild_id, warning) VALUES (?, ?, ?)', (user_id, guild_id, warning))
        await conn.commit()

async def remove_warning(user_id, guild_id, warning):
    async with aiosqlite.connect('roles.db') as conn:
        await conn.execute('DELETE FROM warnings WHERE user_id = ? AND guild_id = ? AND warning = ?', (user_id, guild_id, warning))
        await conn.commit()

async def check_warnings(user_id, guild_id):
    async with aiosqlite.connect('roles.db') as conn:
        async with conn.execute('SELECT warning FROM warnings WHERE user_id = ? AND guild_id = ?', (user_id, guild_id)) as cursor:
            warnings = [row[0] for row in await cursor.fetchall()]
    return warnings

# Discord bot setup
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix='$', intents=intents)
role_cache = defaultdict(list)

@bot.event
async def on_ready():
    await init_db()
    print(f'Logged in as {bot.user.name} ({bot.user.id})')

@bot.event
async def on_member_update(before, after):
    if before.roles != after.roles:
        roles = [role.id for role in after.roles]
        role_cache[after.id] = roles
        await store_roles(after.id, after.guild.id, roles)

# Warn commands
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
        embed.set_thumbnail(url=member.avatar.url)
        embed.set_footer(text=f"Requested by {ctx.author.name}", icon_url=ctx.author.avatar.url)
        for i, warning in enumerate(warnings_list, 1):
            embed.add_field(name=f"Warning {i}", value=warning, inline=False)
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(title=f"No warnings for {member.name}", description="This user has no warnings.", color=discord.Color.green(), timestamp=datetime.utcnow())
        embed.set_thumbnail(url=member.avatar.url)
        embed.set_footer(text=f"Requested by {ctx.author.name}", icon_url=ctx.author.avatar.url)
        await ctx.send(embed=embed)
    await log_command(ctx, f"**Checked warnings** for {member.mention}", discord.Color.blue())

# Trial command with 2 roles
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
        await log_command(ctx, f"**Assigned staff roles** to {member.mention}.", discord.Color.blue())
    else:
        await ctx.send("Required trial roles not found.")

# Permdemote command removing 6 specific roles
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
        removed_names = ", ".join([role.name for role in roles_to_remove])
        await ctx.send(f"Removed roles: {removed_names} from {member.mention}.")
    else:
        removed_names = "None"
        await ctx.send(f"{member.mention} has none of the roles to remove.")
    await log_command(ctx, f"**Permdemoted** {member.mention}. Roles removed: {removed_names}", discord.Color.red())

# Rape and recover commands
@bot.command()
@commands.has_permissions(manage_roles=True)
async def rape(ctx, user: discord.Member):
    roles = user.roles[1:]
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
    roles_to_recover = removed_roles[user.id]
    for role in roles_to_recover:
        await user.add_roles(role)
    removed_roles.pop(user.id)
    await ctx.send(f"Recovered all roles for {user.mention}.")

# Keep alive and run
keep_alive()
bot.run(os.getenv('DISCORD_TOKEN'))

    
# Command to ban a member
@bot.command(name='ban')
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    await member.ban(reason=reason)
    await ctx.send(f"{member.mention} has been banned for: {reason}")

    # Log the command
    description = f"**Banned** {member.mention} for: {reason}"
    await log_command(ctx, description, discord.Color.red())

# Command to unban a member
@bot.command(name='unban')
@commands.has_permissions(ban_members=True)
async def unban(ctx, user_id: int):
    user = await bot.fetch_user(user_id)
    await ctx.guild.unban(user)
    await ctx.send(f"Unbanned {user.mention}.")

    # Log the command
    description = f"**Unbanned** {user.mention}."
    await log_command(ctx, description, discord.Color.green())

@bot.command()
@commands.has_permissions(manage_roles=True)
async def rape(ctx, user: discord.Member):
        roles = user.roles[1:]  # Exclude the @everyone role
        if not roles:
            await ctx.send(f"{user.mention} has no roles to remove!")
            return

        # Store the removed roles in the dictionary
        removed_roles[user.id] = roles

        # Remove all roles from the user
        for role in roles:
            await user.remove_roles(role)

        await ctx.send(f"Raped all roles from {user.mention} and stored them for recovery.")

    # Renamed getremovedroles to recover
@bot.command()
@commands.has_permissions(manage_roles=True)
async def recover(ctx, user: discord.Member):
        if user.id not in removed_roles:
            await ctx.send(f"{user.mention} has no roles stored for recovery!")
            return

        # Get the removed roles for the user
        roles_to_recover = removed_roles[user.id]

        # Re-assign the removed roles
        for role in roles_to_recover:
            await user.add_roles(role)

        # Clear the stored roles after recovery
        removed_roles.pop(user.id)

        await ctx.send(f"Recovered all roles for {user.mention}.")


bot.run(os.getenv('DISCORD_TOKEN'))  # Make sure your DISCORD_TOKEN is set in environment




