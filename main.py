import os
import aiosqlite  # Async SQLite driver
import discord
from discord.ext import commands
from datetime import datetime
from collections import defaultdict
from keep_alive import keep_alive

# Database setup (Async with aiosqlite)
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
        ''')  # New table for removed roles
        await conn.commit()

# Dictionary to store removed roles by user ID
removed_roles = {}


# Function to log commands in an embed to a log channel
async def log_command(ctx, description: str, color: discord.Color):
    log_channel_id = 1289869063895515147  # Replace with your log channel ID
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


# Store roles with async DB operations
async def store_roles(user_id, guild_id, role_ids):
    async with aiosqlite.connect('roles.db') as conn:
        await conn.executemany('''
            INSERT OR IGNORE INTO roles (user_id, guild_id, role_id)
            VALUES (?, ?, ?)
        ''', [(user_id, guild_id, role_id) for role_id in role_ids])
        await conn.commit()

# Store roles with async DB operations
async def store_roles(user_id, guild_id, role_ids):
    async with aiosqlite.connect('roles.db') as conn:
        await conn.executemany('''
            INSERT OR IGNORE INTO roles (user_id, guild_id, role_id)
            VALUES (?, ?, ?)
        ''', [(user_id, guild_id, role_id) for role_id in role_ids])
        await conn.commit()

# Retrieve roles asynchronously
async def get_roles(user_id, guild_id):
    async with aiosqlite.connect('roles.db') as conn:
        async with conn.execute('SELECT role_id FROM roles WHERE user_id = ? AND guild_id = ?', (user_id, guild_id)) as cursor:
            roles = [row[0] for row in await cursor.fetchall()]
    return roles

# Remove roles from the database (async)
async def remove_roles(user_id, guild_id):
    async with aiosqlite.connect('roles.db') as conn:
        await conn.execute('DELETE FROM roles WHERE user_id = ? AND guild_id = ?', (user_id, guild_id))
        await conn.commit()

# Asynchronously add warnings
async def add_warning(user_id, guild_id, warning):
    async with aiosqlite.connect('roles.db') as conn:
        await conn.execute('INSERT OR IGNORE INTO warnings (user_id, guild_id, warning) VALUES (?, ?, ?)', (user_id, guild_id, warning))
        await conn.commit()

# Asynchronously remove warnings
async def remove_warning(user_id, guild_id, warning):
    async with aiosqlite.connect('roles.db') as conn:
        await conn.execute('DELETE FROM warnings WHERE user_id = ? AND guild_id = ? AND warning = ?', (user_id, guild_id, warning))
        await conn.commit()

# Check warnings asynchronously
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

# Caching roles to minimize database queries
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

# Command to warn a member
@bot.command(name='warn')
@commands.has_permissions(manage_roles=True)
async def warn(ctx, member: discord.Member, *, reason: str):
    await add_warning(member.id, ctx.guild.id, reason)
    await ctx.send(f"{member.mention} has been warned for: {reason}")

    # Log the command
    description = f"**Warned** {member.mention} for: {reason}"
    await log_command(ctx, description, discord.Color.orange())

# Command to remove a warning
@bot.command(name='unwarn')
@commands.has_permissions(manage_roles=True)
async def unwarn(ctx, member: discord.Member, *, reason: str):
    await remove_warning(member.id, ctx.guild.id, reason)
    await ctx.send(f"Warning removed for {member.mention}: {reason}")

    # Log the command
    description = f"**Unwarned** {member.mention}. Reason: {reason}"
    await log_command(ctx, description, discord.Color.green())

# Command to check warnings for a member
@bot.command(name='warnings')
@commands.has_permissions(manage_roles=True)
async def warnings(ctx, member: discord.Member):
    warnings = await check_warnings(member.id, ctx.guild.id)

    if warnings:
        # Create the embed
        embed = discord.Embed(
            title=f"Warnings for {member.name}",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow()
        )
        embed.set_thumbnail(url=member.avatar.url)  # User's avatar as thumbnail
        embed.set_footer(text=f"Requested by {ctx.author.name}", icon_url=ctx.author.avatar.url)

        # Add warnings to the embed
        for i, warning in enumerate(warnings, 1):
            embed.add_field(name=f"Warning {i}", value=warning, inline=False)

        await ctx.send(embed=embed)
    else:
        # If no warnings, send an embed saying so
        embed = discord.Embed(
            title=f"No warnings for {member.name}",
            description="This user has no warnings.",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        embed.set_thumbnail(url=member.avatar.url)  # User's avatar as thumbnail
        embed.set_footer(text=f"Requested by {ctx.author.name}", icon_url=ctx.author.avatar.url)

        await ctx.send(embed=embed)

    # Log the command
    description = f"**Checked warnings** for {member.mention}"
    await log_command(ctx, description, discord.Color.blue())

# Command to demote a member and assign a specific role
@bot.command(name='permdemote')
@commands.has_permissions(manage_roles=True)
async def permdemote(ctx, member: discord.Member):
    staff_team_role_id = 1289125001961799690  # Staff Team role ID
    except_role_id = 1290243329145176127      # Replace with actual Except Role ID

    staff_team_role = ctx.guild.get_role(staff_team_role_id)
    except_role = ctx.guild.get_role(except_role_id)

    if not staff_team_role or not except_role:
        await ctx.send("Required roles not found.")
        return

    roles_to_remove = [role for role in member.roles if role.position >= staff_team_role.position]

    if roles_to_remove:
        await member.remove_roles(*roles_to_remove)
        removed_roles = ", ".join([role.name for role in roles_to_remove])
        await ctx.send(f"Removed roles: {removed_roles}")
    else:
        await ctx.send(f"{member.mention} doesn't have roles above {staff_team_role.name}.")

    if except_role not in member.roles:
        await member.add_roles(except_role)
        await ctx.send(f"Assigned {except_role.name} to {member.mention}.")

    # Log the command
    description = f"**Permdemoted** {member.mention}. Roles removed: {removed_roles}"
    await log_command(ctx, description, discord.Color.red())

# Command to assign trial roles
@bot.command(name='trial')
@commands.has_permissions(manage_roles=True)
async def trial(ctx, member: discord.Member):
    role1_id = 1289172691311530055  # Replace with actual Role1 ID
    role2_id = 1289125001961799690  # Replace with actual Role2 ID

    role1 = ctx.guild.get_role(role1_id)
    role2 = ctx.guild.get_role(role2_id)

    if role1 and role2:
        await member.add_roles(role1, role2)
        await ctx.send(f"Assigned {role1.name} and {role2.name} to {member.mention}.")

        # Log the command
        description = f"**Assigned staff roles** to {member.mention}."
        await log_command(ctx, description, discord.Color.blue())

# Command to mute a member
@bot.command(name='mute')
@commands.has_permissions(manage_roles=True)
async def mute(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    mute_role_id = 1291458245747277955  # Mute role ID
    mute_role = ctx.guild.get_role(mute_role_id)

    if not mute_role:
        await ctx.send("Mute role not found.")
        return

    await member.add_roles(mute_role)
    await ctx.send(f"{member.mention} has been muted for: {reason}")

    # Log the command
    description = f"**Muted** {member.mention} for: {reason}"
    await log_command(ctx, description, discord.Color.red())

# Command to unmute a member
@bot.command(name='unmute')
@commands.has_permissions(manage_roles=True)
async def unmute(ctx, member: discord.Member):
    mute_role_id = 1291458245747277955  # Mute role ID
    mute_role = ctx.guild.get_role(mute_role_id)

    if not mute_role:
        await ctx.send("Mute role not found.")
        return

    await member.remove_roles(mute_role)
    await ctx.send(f"{member.mention} has been unmuted.")

    # Log the command
    description = f"**Unmuted** {member.mention}."
    await log_command(ctx, description, discord.Color.green())

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


keep_alive()  # Optional if you're using a web server
bot.run(os.getenv('DISCORD_TOKEN'))  # Ensure you have your token set as an environment variable
