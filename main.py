import os
import sqlite3
import psycopg2
from replit import db
import discord
from discord.ext import commands
from datetime import datetime
from collections import defaultdict
from keep_alive import keep_alive

# Database setup
conn = sqlite3.connect('roles.db')
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

# Function to store roles
def store_roles(user_id, guild_id, role_ids):
    cursor.executemany('''
        INSERT OR IGNORE INTO roles (user_id, guild_id, role_id)
        VALUES (?, ?, ?)
    ''', [(user_id, guild_id, role_id) for role_id in role_ids])
    conn.commit()

# Function to retrieve roles
def get_roles(user_id, guild_id):
    cursor.execute('''
        SELECT role_id FROM roles WHERE user_id = ? AND guild_id = ?
    ''', (user_id, guild_id))
    return [row[0] for row in cursor.fetchall()]

# Function to remove roles from the database
def remove_roles(user_id, guild_id):
    cursor.execute('''
        DELETE FROM roles WHERE user_id = ? AND guild_id = ?
    ''', (user_id, guild_id))
    conn.commit()

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

# Helper function to send log messages
async def send_log(embed):
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel:
        await channel.send(embed=embed)
    else:
        print("Log channel not found.")

# Function to generate formatted time
def get_time_info():
    now = datetime.utcnow()
    gmt_time = now.strftime('%d/%m/%Y, %H:%M:%S')
    return gmt_time

# Dictionary to store warnings
warnings = defaultdict(list)

# Bot ready event
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    print('------')

    # Send a startup log
    gmt_time = get_time_info()
    embed = discord.Embed(title='Bot Started', color=discord.Color.green())
    embed.add_field(name='**Time**', value=f'{gmt_time}\n')
    await send_log(embed)

# Logging: Member join
@bot.event
async def on_member_join(member):
    gmt_time = get_time_info()
    embed = discord.Embed(title='Member Joined', color=discord.Color.green())
    embed.add_field(name='**User**', value=f'{member} ({member.id})\n')
    embed.add_field(name='**Join Time**', value=f'{gmt_time}\n')
    embed.set_thumbnail(url=member.avatar.url)
    await send_log(embed)

# Logging: Member leave
@bot.event
async def on_member_remove(member):
    gmt_time = get_time_info()
    embed = discord.Embed(title='Member Left', color=discord.Color.red())
    embed.add_field(name='**User**', value=f'{member} ({member.id})\n')
    embed.add_field(name='**Leave Time**', value=f'{gmt_time}\n')
    embed.set_thumbnail(url=member.avatar.url)
    await send_log(embed)

# Logging: Member role update and store roles in the database
@bot.event
async def on_member_update(before, after):
    if before.roles != after.roles:
        # Store the updated roles in the database
        roles = [role.id for role in after.roles]
        store_roles(after.id, after.guild.id, roles)

        gmt_time = get_time_info()
        embed = discord.Embed(title='Member Role Updated', color=discord.Color.green())
        embed.add_field(name='**User**', value=f'{after} ({after.id})\n')
        embed.add_field(name='**Before**', value=f'{[role.name for role in before.roles]}\n')
        embed.add_field(name='**After**', value=f'{[role.name for role in after.roles]}\n')
        embed.add_field(name='**Update Time**', value=f'{gmt_time}\n')
        embed.set_thumbnail(url=after.avatar.url)
        await send_log(embed)

# Command: Recover all roles from the database
@bot.command(name='recover')
@commands.has_permissions(manage_roles=True)
async def recover(ctx, member: discord.Member):
    roles_to_restore = get_roles(member.id, ctx.guild.id)
    if roles_to_restore:
        roles = [ctx.guild.get_role(role_id) for role_id in roles_to_restore]
        await member.add_roles(*roles)
        await ctx.send(f"Roles have been restored to {member.mention}.")
        remove_roles(member.id, ctx.guild.id)  # Remove from DB after restoring
    else:
        await ctx.send(f"No roles found to recover for {member.display_name}.")

# Start the bot
bot.run(os.getenv('DISCORD_TOKEN'))
