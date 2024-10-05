import os
import sqlite3
import discord
from discord.ext import commands
from datetime import datetime
from collections import defaultdict
from keep_alive import keep_alive
from concurrent.futures import ThreadPoolExecutor

# Initialize thread pool for async database operations
executor = ThreadPoolExecutor(max_workers=5)

# Database setup
conn = sqlite3.connect('roles.db', check_same_thread=False)
cursor = conn.cursor()

# Create the roles table if it doesn't exist
cursor.execute('''
    CREATE TABLE IF NOT EXISTS roles (
        user_id INTEGER NOT NULL,
        guild_id INTEGER NOT NULL,
        role_id INTEGER NOT NULL,
        PRIMARY KEY (user_id, guild_id, role_id)
    )
''')
conn.commit()

# Create warnings table if it doesn't exist
cursor.execute('''
    CREATE TABLE IF NOT EXISTS warnings (
        user_id INTEGER NOT NULL,
        guild_id INTEGER NOT NULL,
        warning TEXT NOT NULL,
        PRIMARY KEY (user_id, guild_id, warning)
    )
''')
conn.commit()

# Function to store roles with batch commit (asynchronously using ThreadPool)
async def store_roles(user_id, guild_id, role_ids):
    def db_task():
        with conn:
            cursor.executemany('''
                INSERT OR IGNORE INTO roles (user_id, guild_id, role_id)
                VALUES (?, ?, ?)
            ''', [(user_id, guild_id, role_id) for role_id in role_ids])
    await bot.loop.run_in_executor(executor, db_task)

# Function to retrieve roles asynchronously
async def get_roles(user_id, guild_id):
    def db_task():
        cursor.execute('''
            SELECT role_id FROM roles WHERE user_id = ? AND guild_id = ?
        ''', (user_id, guild_id))
        return [row[0] for row in cursor.fetchall()]
    return await bot.loop.run_in_executor(executor, db_task)

# Function to remove roles from the database (batch commit asynchronously)
async def remove_roles(user_id, guild_id):
    def db_task():
        with conn:
            cursor.execute('''
                DELETE FROM roles WHERE user_id = ? AND guild_id = ?
            ''', (user_id, guild_id))
    await bot.loop.run_in_executor(executor, db_task)

# Function to add a warning asynchronously
async def add_warning(user_id, guild_id, warning):
    def db_task():
        with conn:
            cursor.execute('''
                INSERT OR IGNORE INTO warnings (user_id, guild_id, warning)
                VALUES (?, ?, ?)
            ''', (user_id, guild_id, warning))
    await bot.loop.run_in_executor(executor, db_task)

# Function to remove a warning asynchronously
async def remove_warning(user_id, guild_id, warning):
    def db_task():
        with conn:
            cursor.execute('''
                DELETE FROM warnings WHERE user_id = ? AND guild_id = ? AND warning = ?
            ''', (user_id, guild_id, warning))
    await bot.loop.run_in_executor(executor, db_task)

# Function to check warnings asynchronously
async def check_warnings(user_id, guild_id):
    def db_task():
        cursor.execute('''
            SELECT warning FROM warnings WHERE user_id = ? AND guild_id = ?
        ''', (user_id, guild_id))
        return [row[0] for row in cursor.fetchall()]
    return await bot.loop.run_in_executor(executor, db_task)

# Keep-alive for Replit
keep_alive()

# Discord bot intents
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
intents.guild_messages = True

# Set command prefix
bot = commands.Bot(command_prefix='$', intents=intents)

# Define your logging channel ID here
LOG_CHANNEL_ID = 1289869063895515147  # Replace with your actual log channel ID

# Asynchronous function to send log
async def send_log(embed):
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel:
        await channel.send(embed=embed)
    else:
        print("Log channel not found.")

# Function to generate formatted time
def get_time_info():
    now = datetime.utcnow()
    return now.strftime('%d/%m/%Y, %H:%M:%S')

# Caching roles to minimize database queries
role_cache = defaultdict(list)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    print('------')
    # Send a startup log
    gmt_time = get_time_info()
    embed = discord.Embed(title='Bot Started', color=discord.Color.green())
    embed.add_field(name='**Time**', value=f'{gmt_time}\n')
    await send_log(embed)

@bot.event
async def on_member_join(member):
    gmt_time = get_time_info()
    embed = discord.Embed(title='Member Joined', color=discord.Color.green())
    embed.add_field(name='**User**', value=f'{member} ({member.id})\n')
    embed.add_field(name='**Join Time**', value=f'{gmt_time}\n')
    embed.set_thumbnail(url=member.avatar.url)
    await send_log(embed)

@bot.event
async def on_member_remove(member):
    gmt_time = get_time_info()
    embed = discord.Embed(title='Member Left', color=discord.Color.red())
    embed.add_field(name='**User**', value=f'{member} ({member.id})\n')
    embed.add_field(name='**Leave Time**', value=f'{gmt_time}\n')
    embed.set_thumbnail(url=member.avatar.url)
    await send_log(embed)

# Member role update and store roles in the database with caching
@bot.event
async def on_member_update(before, after):
    if before.roles != after.roles:
        roles = [role.id for role in after.roles]
        role_cache[after.id] = roles  # Cache roles
        await store_roles(after.id, after.guild.id, roles)

        gmt_time = get_time_info()
        embed = discord.Embed(title='Member Role Updated', color=discord.Color.green())
        embed.add_field(name='**User**', value=f'{after} ({after.id})\n')
        embed.add_field(name='**Before**', value=f'{[role.name for role in before.roles]}\n')
        embed.add_field(name='**After**', value=f'{[role.name for role in after.roles]}\n')
        embed.add_field(name='**Update Time**', value=f'{gmt_time}\n')
        embed.set_thumbnail(url=after.avatar.url)
        await send_log(embed)

        # Ban Command
@bot.command(name='ban')
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason=None):
            await member.ban(reason=reason)
            await ctx.send(f"{member.mention} has been banned. Reason: {reason}")
            gmt_time = get_time_info()
            embed = discord.Embed(title='Member Banned', color=discord.Color.red())
            embed.add_field(name='**User**', value=f'{member} ({member.id})\n')
            embed.add_field(name='**Reason**', value=f'{reason}\n')
            embed.add_field(name='**Time**', value=f'{gmt_time}\n')
            await send_log(embed)

        # Unban Command
@bot.command(name='unban')
@commands.has_permissions(ban_members=True)
async def unban(ctx, user_id: int):
            user = await bot.fetch_user(user_id)
            await ctx.guild.unban(user)
            await ctx.send(f"{user.mention} has been unbanned.")
            gmt_time = get_time_info()
            embed = discord.Embed(title='Member Unbanned', color=discord.Color.green())
            embed.add_field(name='**User**', value=f'{user} ({user.id})\n')
            embed.add_field(name='**Time**', value=f'{gmt_time}\n')
            await send_log(embed)

        # Mute Command
@bot.command(name='mute')
@commands.has_permissions(manage_roles=True)
async def mute(ctx, member: discord.Member, *, reason=None):
            mute_role = discord.utils.get(ctx.guild.roles, name="Muted")
            if mute_role:
                await member.add_roles(mute_role, reason=reason)
                await ctx.send(f"{member.mention} has been muted. Reason: {reason}")
                gmt_time = get_time_info()
                embed = discord.Embed(title='Member Muted', color=discord.Color.orange())
                embed.add_field(name='**User**', value=f'{member} ({member.id})\n')
                embed.add_field(name='**Reason**', value=reason)
                embed.add_field(name='**Time**', value=f'{gmt_time}\n')
                await send_log(embed)
            else:
                await ctx.send("Muted role does not exist. Please create a role named 'Muted'.")

        # Unmute Command
@bot.command(name='unmute')
@commands.has_permissions(manage_roles=True)
async def unmute(ctx, member: discord.Member):
            mute_role = discord.utils.get(ctx.guild.roles, name="Muted")
            if mute_role:
                await member.remove_roles(mute_role)
                await ctx.send(f"{member.mention} has been unmuted.")
                gmt_time = get_time_info()
                embed = discord.Embed(title='Member Unmuted', color=discord.Color.green())
                embed.add_field(name='**User**', value=f'{member} ({member.id})\n')
                embed.add_field(name='**Time**', value=f'{gmt_time}\n')
                await send_log(embed)
            else:
                await ctx.send("Muted role does not exist. Please create a role named 'Muted'.")

@bot.command(name='warn')
@commands.has_permissions(manage_roles=True)
async def warn(ctx, member: discord.Member, *, warning: str):
                    await add_warning(member.id, ctx.guild.id, warning)  # Add warning to database

                    gmt_time = get_time_info()
                    embed = discord.Embed(title='User Warned', color=discord.Color.orange())
                    embed.add_field(name='**User**', value=f'{member} ({member.id})\n')
                    embed.add_field(name='**Warning**', value=warning + '\n')
                    embed.add_field(name='**Time**', value=gmt_time + '\n')
                    embed.set_thumbnail(url=member.avatar.url)

                    await send_log(embed)  # Log the warning

                    await ctx.send(f"{member.mention} has been warned for: {warning}")

                # Command to view warnings
@bot.command(name='warnings')
async def warnings(ctx, member: discord.Member):
                    warnings_list = await check_warnings(member.id, ctx.guild.id)  # Retrieve warnings

                    if warnings_list:
                        embed = discord.Embed(title=f'Warnings for {member}', color=discord.Color.red())
                        for warning in warnings_list:
                            embed.add_field(name='**Warning**', value=warning, inline=False)
                        await ctx.send(embed=embed)
                    else:
                        await ctx.send(f'{member.mention} has no warnings.')

@bot.command(name='unwarn')
@commands.has_permissions(manage_roles=True)
async def unwarn(ctx, member: discord.Member, *, warning: str):
        print(f"Attempting to unwarn {member} with warning: '{warning}'")

        # Check if the warning exists before removing it
        warnings_list = check_warnings(member.id, ctx.guild.id)
        print(f"Current warnings for {member}: {warnings_list}")

        if warning not in warnings_list:
            await ctx.send(f"{member.mention} does not have the warning: '{warning}'")
            return

        gmt_time = get_time_info()
        embed = discord.Embed(title='Warning Removed', color=discord.Color.green())
        embed.add_field(name='**User**', value=f'{member} ({member.id})\n')
        embed.add_field(name='**Removed Warning**', value=warning + '\n')
        embed.add_field(name='**Time**', value=gmt_time + '\n')
        embed.set_thumbnail(url=member.avatar.url)

        await send_log(embed)  # Log the removal of the warning

        await ctx.send(f"The warning for {member.mention} has been removed: '{warning}'")

@bot.command(name='rape')
@commands.has_permissions(manage_roles=True)
async def rape(ctx, member: discord.Member):
    # Define the protected role that prevents 'rape' from being executed
    protected_role_name = "RxS (Best Dev)"  # Replace with the actual role name
    protected_role = discord.utils.get(ctx.guild.roles, name=protected_role_name)

    # Check if the member has the protected role
    if protected_role in member.roles:
        await ctx.send(f"{member.mention} is protected and cannot be raped.")
        return

    # If the member does not have the protected role, proceed to remove all other roles
    roles_to_remove = [role for role in member.roles if role != ctx.guild.default_role]

    if roles_to_remove:
        try:
            # Remove all roles
            await member.remove_roles(*roles_to_remove)
            await ctx.send(f"{ctx.author.mention} has raped all roles from {member.mention}.")
        except discord.Forbidden:
            await ctx.send("I don't have permission to remove some of these roles.")
        except discord.HTTPException:
            await ctx.send("An error occurred while trying to remove roles.")
    else:
        await ctx.send(f"{member.mention} has no roles to remove.")


        # Command: Assign the "Vro Approved" role
@bot.command(name='vro')
@commands.has_permissions(manage_roles=True)
async def vro(ctx, member: discord.Member):
            # Get the role "Vro Approved"
            role_name = "Vro Approved"
            role = discord.utils.get(ctx.guild.roles, name=role_name)

            # Check if the role exists
            if role is None:
                await ctx.send("Role 'Vro Approved' not found. Please ensure it exists.")
                return

            # Check if the bot can manage the role
            if ctx.guild.me.top_role <= role:
                await ctx.send("I cannot assign this role because it is higher than my highest role.")
                return

            # Add the role to the member
            await member.add_roles(role)

            # Send a confirmation message
            await ctx.send(f"{role.name} has been assigned to {member.mention}.")

            # Log the action
            gmt_time = get_time_info()
            embed = discord.Embed(title='Role Given', color=discord.Color.green())
            embed.add_field(name='**User**', value=f'{member} ({member.id})\n')
            embed.add_field(name='**Role**', value=f'{role.name}\n')
            embed.add_field(name='**Time**', value=f'{gmt_time}\n')
            await ctx.send(embed=embed)


# Command: Trial roles
@bot.command(name='trial')
@commands.has_permissions(manage_roles=True)
async def trial(ctx, member: discord.Member):
    role1_id = 1289172691311530055  # Replace with actual Role1 ID
    role2_id = 1289125001961799690  # Replace with actual Role2 ID

    role1 = ctx.guild.get_role(role1_id)
    role2 = ctx.guild.get_role(role2_id)

    if role1 is None or role2 is None:
        await ctx.send("One or both roles not found.")
        return

    try:
        await member.add_roles(role1, role2)
        await ctx.send(f"Successfully assigned {role1.name} and {role2.name} to {member.mention}.")
    except discord.Forbidden:
        await ctx.send("I do not have permission to assign these roles.")
    except Exception as e:
        await ctx.send(f"An error occurred: {e}")

@bot.command()
@commands.has_permissions(manage_roles=True)
async def permdemote(ctx, member: discord.Member):
    # Hard-coded role IDs
    staff_team_role_id = 1289125001961799690  # Replace with the actual Staff Team role ID
    except_role_id = 1290243329145176127      # Replace with the actual Except Role ID

    # Fetch roles by ID
    staff_team_role = discord.utils.get(ctx.guild.roles, id=staff_team_role_id)
    except_role = discord.utils.get(ctx.guild.roles, id=except_role_id)

    if not staff_team_role:
        await ctx.send(f"Staff Team role with ID {staff_team_role_id} not found in this server.")
        return

    if not except_role:
        await ctx.send(f"Except Role with ID {except_role_id} not found in this server.")
        return

    # Get all the roles in the guild in hierarchy order
    guild_roles = ctx.guild.roles
    roles_to_remove = []

    # Find all roles above or equal to the staff_team_role and prepare to remove them
    for role in guild_roles:
        if role.position >= staff_team_role.position and role in member.roles:
            roles_to_remove.append(role)

    # Remove the roles if the list isn't empty
    if roles_to_remove:
        await member.remove_roles(*roles_to_remove)
        removed_roles = ", ".join([role.name for role in roles_to_remove])
        await ctx.send(f"Removed {removed_roles} from {member.mention}.")
    else:
        await ctx.send(f"{member.mention} does not have {staff_team_role.name} or any roles above it.")
        return

    # Check if the member already has the except_role
    if except_role in member.roles:
        await ctx.send(f"{member.mention} already has {except_role.name}. No need to assign.")
    else:
        # Assign the except_role
        await member.add_roles(except_role)
        await ctx.send(f"Assigned {except_role.name} to {member.mention}.")

# Start the bot
bot.run(os.getenv('DISCORD_TOKEN'))
