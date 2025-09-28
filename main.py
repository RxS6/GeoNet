import os
import sqlite3
import aiosqlite
import discord
from discord.ext import commands
from datetime import datetime, timezone
from collections import defaultdict
from keep_alive import keep_alive
import asyncio
from discord.ui import View, Button
import aiohttp
import random
from discord.ui import View, Select

# =========================
# CONFIG / IDS
# =========================
log_channel_id = 1418641633750159493
staff_role1_id = 1418641632236011662
staff_role2_id = 1418641632148066431
autorole_id = 1418641632059850878
ANTINUKE_ROLE_ID = 1418641632236011669
LOG_CHANNEL_ID = 1418641633750159493
WHITELIST_ROLE_ID = 1418641632236011667

# storage for ephemeral features
removed_roles = {}            # for rape/recover command
spam_tracker = defaultdict(list)  # anti-spam tracker

DB_PATH = "roles.db"

# =========================
# DATABASE (cases table) - safe init with integrity check
# =========================
def ensure_db_file():
    # If file exists, run integrity check. If it fails, remove file.
    if os.path.exists(DB_PATH):
        try:
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            cur.execute("PRAGMA integrity_check;")
            res = cur.fetchone()
            con.close()
            if not res or res[0] != "ok":
                print("⚠️ roles.db integrity check failed -> removing corrupt DB and recreating.")
                os.remove(DB_PATH)
        except sqlite3.DatabaseError:
            print("⚠️ roles.db is not a valid sqlite DB -> removing and recreating.")
            try:
                os.remove(DB_PATH)
            except Exception:
                pass

async def init_db():
    # Ensure DB file is valid (or removed) before using aiosqlite
    ensure_db_file()
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS cases (
                case_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                reason TEXT,
                timestamp TEXT
            )
        ''')
        await conn.commit()

async def add_case(guild_id: int, user_id: int, moderator_id: int, action: str, reason: str):
    ts = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            'INSERT INTO cases (guild_id, user_id, moderator_id, action, reason, timestamp) VALUES (?, ?, ?, ?, ?, ?)',
            (guild_id, user_id, moderator_id, action, reason, ts)
        )
        await conn.commit()
        async with conn.execute('SELECT last_insert_rowid()') as cur:
            row = await cur.fetchone()
            return row[0] if row else None

async def get_user_cases(guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            'SELECT case_id, moderator_id, action, reason, timestamp FROM cases WHERE guild_id = ? AND user_id = ? ORDER BY case_id ASC',
            (guild_id, user_id)
        ) as cursor:
            return await cursor.fetchall()

async def get_case_by_id(guild_id: int, case_id: int):
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            'SELECT case_id, guild_id, user_id, moderator_id, action, reason, timestamp FROM cases WHERE case_id = ? AND guild_id = ?',
            (case_id, guild_id)
        ) as cur:
            return await cur.fetchone()

async def remove_case(case_id: int):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute('DELETE FROM cases WHERE case_id = ?', (case_id,))
        await conn.commit()

async def get_case_counts(guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            'SELECT action, COUNT(*) FROM cases WHERE guild_id = ? AND user_id = ? GROUP BY action',
            (guild_id, user_id)
        ) as cur:
            rows = await cur.fetchall()
            counts = {"Warn": 0, "Mute": 0, "Kick": 0, "Ban": 0}
            for action, cnt in rows:
                if action in counts:
                    counts[action] = cnt
            return counts

# =========================
# BOT setup
# =========================
intents = discord.Intents.all()

# multiple prefixes ($ and !), plus mention
bot = commands.Bot(
    command_prefix=commands.when_mentioned_or("$", "/"),
    intents=intents
)

# remove default help to use custom one
try:
    bot.remove_command("help")
except Exception:
    pass

@bot.event
async def on_ready():
    # ensure DB and tables exist (and recreate if needed)
    await init_db()
    print(f'✅ Logged in as {bot.user} ({bot.user.id})')

    
# =========================
# Autorole
# =========================
@bot.event
async def on_member_join(member):
    role = member.guild.get_role(autorole_id)
    if role:
        try:
            await member.add_roles(role)
        except Exception:
            pass

        general_channel = member.guild.get_channel(1418641633322336349)  # General ka ID daal yaha
        if general_channel:
            await general_channel.send(
                f"👋 Welcome {member.mention}, you’ve been given <@&{role.id}>!"
            )
            # =========================

# EXTENDED LOGGING SYSTEM (All Activities except Guild Events)
# =========================
async def send_log(guild, embed: discord.Embed):
    try:
        log_channel = guild.get_channel(log_channel_id)
        if log_channel:
            await log_channel.send(embed=embed)
    except Exception:
        pass


# -------------------------
# Messages
# -------------------------
@bot.event
async def on_message_delete(message):
    if message.author.bot: return
    embed = discord.Embed(
        title="🗑️ Message Deleted",  # fa-trash
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="User", value=message.author.mention, inline=False)
    embed.add_field(name="Channel", value=message.channel.mention, inline=False)
    embed.add_field(name="Content", value=message.content or "*Empty*", inline=False)
    await send_log(message.guild, embed)


@bot.event
async def on_message_edit(before, after):
    if before.author.bot: return
    if before.content == after.content: return
    embed = discord.Embed(
        title="✏️ Message Edited",  # fa-pencil-alt
        color=discord.Color.orange(),
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="User", value=before.author.mention, inline=False)
    embed.add_field(name="Channel", value=before.channel.mention, inline=False)
    embed.add_field(name="Before", value=before.content or "*Empty*", inline=False)
    embed.add_field(name="After", value=after.content or "*Empty*", inline=False)
    await send_log(before.guild, embed)


# -------------------------
# Member Events
# -------------------------
@bot.event
async def on_member_join(member):
    embed = discord.Embed(
        title="👤➕ Member Joined",  # fa-user-plus
        description=f"{member.mention} joined the server!",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    await send_log(member.guild, embed)


@bot.event
async def on_member_remove(member):
    embed = discord.Embed(
        title="👤➖ Member Left",  # fa-user-minus
        description=f"{member} has left the server.",
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc)
    )
    await send_log(member.guild, embed)


@bot.event
async def on_member_ban(guild, user):
    embed = discord.Embed(
        title="⛔ Member Banned",  # fa-ban
        description=f"{user} was banned from the server.",
        color=discord.Color.dark_red(),
        timestamp=datetime.now(timezone.utc)
    )
    await send_log(guild, embed)


@bot.event
async def on_member_unban(guild, user):
    embed = discord.Embed(
        title="♻️ Member Unbanned",  # fa-sync
        description=f"{user} was unbanned.",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc)
    )
    await send_log(guild, embed)


@bot.event
async def on_member_update(before, after):
    embed = discord.Embed(
        title="👤 Member Updated",  # fa-user
        color=discord.Color.blue(),
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="User", value=after.mention, inline=False)

    if before.nick != after.nick:
        embed.add_field(name="Nickname", value=f"`{before.nick}` → `{after.nick}`", inline=False)

    if before.roles != after.roles:
        before_roles = ", ".join([r.mention for r in before.roles if r != before.guild.default_role])
        after_roles = ", ".join([r.mention for r in after.roles if r != after.guild.default_role])
        embed.add_field(name="Roles Before", value=before_roles or "None", inline=False)
        embed.add_field(name="Roles After", value=after_roles or "None", inline=False)

    await send_log(after.guild, embed)


# -------------------------
# Voice Events
# -------------------------
@bot.event
async def on_voice_state_update(member, before, after):
    if before.channel != after.channel:
        if before.channel is None:
            desc = f"{member.mention} joined {after.channel.mention}"
            title = "🎙️➕ Voice Join"  # fa-microphone
            color = discord.Color.green()
        elif after.channel is None:
            desc = f"{member.mention} left {before.channel.mention}"
            title = "🎙️➖ Voice Leave"  # fa-microphone-slash
            color = discord.Color.red()
        else:
            desc = f"{member.mention} switched {before.channel.mention} → {after.channel.mention}"
            title = "🔀 Voice Switch"  # fa-random
            color = discord.Color.orange()

        embed = discord.Embed(
            title=title,
            description=desc,
            color=color,
            timestamp=datetime.now(timezone.utc)
        )
        await send_log(member.guild, embed)

    # Mute/deafen/stream/video changes
    changes = []
    if before.self_mute != after.self_mute:
        changes.append("🔇 Muted" if after.self_mute else "🔊 Unmuted")  # fa-microphone-slash
    if before.self_deaf != after.self_deaf:
        changes.append("🙉 Deafened" if after.self_deaf else "👂 Undeafened")  # fa-deaf
    if before.self_stream != after.self_stream:
        changes.append("📺 Started Streaming" if after.self_stream else "🛑 Stopped Streaming")  # fa-desktop
    if before.self_video != after.self_video:
        changes.append("📹 Camera On" if after.self_video else "📷 Camera Off")  # fa-video

    if changes:
        embed = discord.Embed(
            title="🎧 Voice State Updated",  # fa-headphones
            description=f"{member.mention}\n" + "\n".join(changes),
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc)
        )
        await send_log(member.guild, embed)


# -------------------------
# Channel Events
# -------------------------
@bot.event
async def on_guild_channel_create(channel):
    embed = discord.Embed(
        title="📂➕ Channel Created",  # fa-folder-plus
        description=f"Channel {channel.mention} created.",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc)
    )
    await send_log(channel.guild, embed)


@bot.event
async def on_guild_channel_delete(channel):
    embed = discord.Embed(
        title="📂➖ Channel Deleted",  # fa-folder-minus
        description=f"Channel `{channel.name}` deleted.",
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc)
    )
    await send_log(channel.guild, embed)


@bot.event
async def on_guild_channel_update(before, after):
    if before.name != after.name:
        embed = discord.Embed(
            title="📂✏️ Channel Renamed",  # fa-edit
            description=f"`{before.name}` → `{after.name}`",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc)
        )
        await send_log(after.guild, embed)


# -------------------------
# Role Events
# -------------------------
@bot.event
async def on_guild_role_create(role):
    embed = discord.Embed(
        title="🎭➕ Role Created",  # fa-id-badge
        description=f"Role {role.mention} created.",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc)
    )
    await send_log(role.guild, embed)


@bot.event
async def on_guild_role_delete(role):
    embed = discord.Embed(
        title="🎭➖ Role Deleted",  # fa-id-badge
        description=f"Role `{role.name}` deleted.",
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc)
    )
    await send_log(role.guild, embed)


@bot.event
async def on_guild_role_update(before, after):
    changes = []
    if before.name != after.name:
        changes.append(f"Name: `{before.name}` → `{after.name}`")
    if before.color != after.color:
        changes.append(f"Color: `{before.color}` → `{after.color}`")

    if changes:
        embed = discord.Embed(
            title="🎭✏️ Role Updated",  # fa-id-badge
            description="\n".join(changes),
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc)
        )
        await send_log(after.guild, embed)
        
# =========================
# AutoMod (Wick-style)
# =========================
spam_tracker = defaultdict(list)
mention_tracker = defaultdict(list)

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    now = datetime.now(timezone.utc).timestamp()

    # =========================
    # Anti-Spam
    # =========================
    last_times = spam_tracker[message.author.id]
    spam_tracker[message.author.id] = [t for t in last_times if now - t < 5]
    spam_tracker[message.author.id].append(now)

    if len(spam_tracker[message.author.id]) >= 5:  # 5 msgs in 5 sec
        mute_role = discord.utils.get(message.guild.roles, name="Muted")
        if mute_role:
            try:
                await message.author.add_roles(mute_role, reason="Auto-muted for spamming")
                await message.channel.send(f"🤐 {message.author.mention} muted for spamming.")
            except:
                pass

            embed = discord.Embed(
                title="🚨 AutoMod: Spam Detected",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
            embed.add_field(name="User", value=message.author.mention, inline=False)
            embed.add_field(name="Action", value="Muted", inline=True)
            embed.add_field(name="Reason", value="Spamming messages", inline=True)
            embed.add_field(name="Channel", value=message.channel.mention, inline=False)
            embed.set_footer(text=f"User ID: {message.author.id}")

            await send_log(message.guild, embed)
        spam_tracker[message.author.id] = []

    # =========================
    # Anti-Link (Discord Invites)
    # =========================
    if "discord.gg/" in message.content or "discord.com/invite/" in message.content:
        try:
            await message.delete()
        except:
            pass

        embed = discord.Embed(
            title="🔗 AutoMod: Invite Link Blocked",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
        embed.add_field(name="User", value=message.author.mention, inline=False)
        embed.add_field(name="Action", value="Message Deleted", inline=True)
        embed.add_field(name="Reason", value="Posted Invite Link", inline=True)
        embed.add_field(name="Channel", value=message.channel.mention, inline=False)
        embed.set_footer(text=f"User ID: {message.author.id}")

        await send_log(message.guild, embed)

    # =========================
    # Anti-Mass Mentions
    # =========================
    if len(message.mentions) >= 5:
        try:
            await message.delete()
        except:
            pass

        mute_role = discord.utils.get(message.guild.roles, name="Muted")
        if mute_role:
            try:
                await message.author.add_roles(mute_role, reason="Mass mentions")
            except:
                pass

        embed = discord.Embed(
            title="🚨 AutoMod: Mass Mentions",
            color=discord.Color.dark_red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
        embed.add_field(name="User", value=message.author.mention, inline=False)
        embed.add_field(name="Action", value="Muted", inline=True)
        embed.add_field(name="Reason", value=f"Tagged {len(message.mentions)} users", inline=True)
        embed.add_field(name="Channel", value=message.channel.mention, inline=False)
        embed.set_footer(text=f"User ID: {message.author.id}")

        await send_log(message.guild, embed)

    await bot.process_commands(message)

# =========================
# DATABASE SETUP
# =========================
async def setup_database():
    async with aiosqlite.connect("bot.db") as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS antinuke (
            guild_id INTEGER PRIMARY KEY,
            enabled INTEGER DEFAULT 0
        )
    ''')
    await db.execute('''
        CREATE TABLE IF NOT EXISTS antinuke_whitelist (
            guild_id INTEGER,
            user_id INTEGER,
            PRIMARY KEY (guild_id, user_id)
        )
    ''')
    await db.execute('''
        CREATE TABLE IF NOT EXISTS antinuke_logs (
            guild_id INTEGER PRIMARY KEY,
            channel_id INTEGER
        )
    ''')
    await db.execute('''
        CREATE TABLE IF NOT EXISTS cases (
            case_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            reason TEXT,
            timestamp TEXT
        )
    ''')
    await db.execute('''
        CREATE TABLE IF NOT EXISTS deleted_messages (
            guild_id INTEGER,
            channel_id INTEGER,
            message_id INTEGER,
            author_id INTEGER,
            content TEXT,
            attachments TEXT,
            timestamp TEXT
        )
    ''')
    await db.commit()

# =========================
# ENABLE / DISABLE / STATUS
# =========================
@bot.command(name="antinuke-enable")
async def antinuke_enable(ctx):
    if ANTINUKE_ROLE_ID not in [r.id for r in ctx.author.roles]:
        return await ctx.send("❌ You don’t have permission")
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("INSERT OR REPLACE INTO antinuke (guild_id, enabled) VALUES (?, ?)", (ctx.guild.id, 1))
        await db.commit()
    await ctx.send("✅ Anti-Nuke enabled")

@bot.command(name="antinuke-disable")
async def antinuke_disable(ctx):
    if ANTINUKE_ROLE_ID not in [r.id for r in ctx.author.roles]:
        return await ctx.send("❌ You don’t have permission")
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("INSERT OR REPLACE INTO antinuke (guild_id, enabled) VALUES (?, ?)", (ctx.guild.id, 0))
        await db.commit()
    await ctx.send("⚠️ Anti-Nuke disabled")

@bot.command(name="antinuke-status")
async def antinuke_status(ctx):
    enabled = await is_enabled(ctx.guild.id)
    status = "🟢 Enabled" if enabled else "🔴 Disabled"
    await ctx.send(f"📊 Anti-Nuke Status: {status}")

# =========================
# WHITELIST MANAGEMENT
# =========================
@bot.command(name="antinuke-whitelist-add")
async def whitelist_add(ctx, user: discord.Member):
    if ANTINUKE_ROLE_ID not in [r.id for r in ctx.author.roles]:
        return await ctx.send("❌ No permission")
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("INSERT OR IGNORE INTO antinuke_whitelist (guild_id, user_id) VALUES (?, ?)", (ctx.guild.id, user.id))
        await db.commit()
    await ctx.send(f"✅ {user.mention} added to whitelist")

@bot.command(name="antinuke-whitelist-remove")
async def whitelist_remove(ctx, user: discord.Member):
    if ANTINUKE_ROLE_ID not in [r.id for r in ctx.author.roles]:
        return await ctx.send("❌ No permission")
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("DELETE FROM antinuke_whitelist WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, user.id))
        await db.commit()
    await ctx.send(f"✅ {user.mention} removed from whitelist")

@bot.command(name="antinuke-whitelist-list")
async def whitelist_list(ctx):
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("SELECT user_id FROM antinuke_whitelist WHERE guild_id = ?", (ctx.guild.id,))
        rows = await cursor.fetchall()
    if not rows: return await ctx.send("❌ No whitelisted users")
    mentions = [ctx.guild.get_member(r[0]).mention if ctx.guild.get_member(r[0]) else f"User ID {r[0]}" for r in rows]
    await ctx.send("📋 Whitelisted Users:\n" + "\n".join(mentions))

# =========================
# EVENT LISTENERS
# =========================
@bot.event
async def on_guild_role_delete(role):
    if not await is_enabled(role.guild.id): return
    if await is_whitelisted(role.guild.id, role.guild.owner_id): return
    await role.guild.create_role(name=role.name, permissions=role.permissions, colour=role.color,
                                 hoist=role.hoist, mentionable=role.mentionable, reason="Anti-Nuke: Role Restore")
    await log_event(role.guild, f"Role {role.name} deleted and restored")

@bot.event
async def on_guild_channel_delete(channel):
    if not await is_enabled(channel.guild.id): return
    overwrites = channel.overwrites
    await channel.guild.create_text_channel(name=channel.name, overwrites=overwrites, category=channel.category,
                                            reason="Anti-Nuke: Channel Restore")
    await log_event(channel.guild, f"Channel {channel.name} deleted and restored")

@bot.event
async def on_guild_emojis_update(guild, before, after):
    if not await is_enabled(guild.id): return
    before_names = [e.name for e in before]
    after_names = [e.name for e in after]
    deleted = [e for e in before if e.name not in after_names]
    for e in deleted:
        await guild.create_custom_emoji(name=e.name, image=await e.url.read(), reason="Anti-Nuke: Emoji Restore")
        await log_event(guild, f"Emoji {e.name} deleted and restored")

@bot.event
async def on_webhooks_update(channel):
    if not await is_enabled(channel.guild.id): return
    await log_event(channel.guild, f"Webhook change detected in {channel.name}")

@bot.event
async def on_guild_role_update(before, after):
    if not await is_enabled(before.guild.id): return
    await after.edit(permissions=before.permissions, reason="Anti-Nuke: Role Permissions Restore")
    await log_event(before.guild, f"Role {after.name} permissions reverted")

@bot.event
async def on_guild_channel_update(before, after):
    if not await is_enabled(before.guild.id): return
    await after.edit(overwrites=before.overwrites, name=before.name, category=before.category,
                     topic=getattr(before, "topic", None), reason="Anti-Nuke: Channel Overwrites Revert")
    await log_event(before.guild, f"Channel {after.name} reverted")

@bot.event
async def on_message_delete(message):
    if not await is_enabled(message.guild.id): return
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("INSERT INTO deleted_messages (guild_id, channel_id, message_id, author_id, content, attachments, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (message.guild.id, message.channel.id, message.id, message.author.id, message.content, ",".join([a.url for a in message.attachments]), str(message.created_at)))
        await db.commit()
    await log_event(message.guild, f"Message deleted in {message.channel.name} stored for recovery")

# =========================
# LOGGING
# =========================
async def log_event(guild, message):
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("SELECT channel_id FROM antinuke_logs WHERE guild_id = ?", (guild.id,))
        row = await cursor.fetchone()
    if row:
        ch = guild.get_channel(row[0])
        if ch: await ch.send(f"🛡️ {message}")

# =========================
# HELPERS
# =========================
async def is_enabled(guild_id):
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("SELECT enabled FROM antinuke WHERE guild_id = ?", (guild_id,))
        row = await cursor.fetchone()
    return bool(row[0]) if row else False

async def is_whitelisted(guild_id, user_id):
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("SELECT 1 FROM antinuke_whitelist WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        row = await cursor.fetchone()
    return bool(row)

# =========================
# STAFF / FUN commands (trial, permdemote, rape/recover)
# =========================
@bot.command(name='trial')
@commands.has_permissions(manage_roles=True)
async def trial(ctx, member: discord.Member):
    role1 = ctx.guild.get_role(staff_role1_id)
    role2 = ctx.guild.get_role(staff_role2_id)
    if role1 and role2:
        try:
            await member.add_roles(role1, role2)
        except Exception:
            pass
        await ctx.send(f"✅ Assigned <@&{role1.id}> and <@&{role2.id}> to {member.mention}.")
        await log_command(ctx, f"Assigned trial roles to {member.mention}.", discord.Color.blue())
    else:
        await ctx.send("⚠️ Required trial roles not found.")

@bot.command(name='cmd_permdemote')
@commands.has_permissions(manage_roles=True)
async def cmd_permdemote(ctx, member: discord.Member):
    role_ids_to_remove = [
        1418641632148066431,
        1418641632148066432,
        1418641632148066433,
        1418641632148066434,
        1418641632148066435,
        1418641632236011661,
        1418641632236011662,
        1418641632236011663,
        1418641632236011664,
        1418641632236011665
    ]
    roles_to_remove = [ctx.guild.get_role(rid) for rid in role_ids_to_remove if ctx.guild.get_role(rid) in member.roles]
    if roles_to_remove:
        try:
            await member.remove_roles(*roles_to_remove)
        except Exception:
            pass
        mentions = " ".join([f"<@&{r.id}>" for r in roles_to_remove])
        await ctx.send(f"✅ Removed {mentions} from {member.mention}.")
        await log_command(ctx, f"Permdemoted {member.mention}. Roles removed: {mentions}", discord.Color.red())
    else:
        await ctx.send(f"{member.mention} has none of the target roles.")

@bot.command()
@commands.has_permissions(manage_roles=True)
async def rape(ctx, user: discord.Member):
    roles = user.roles[1:]
    if not roles:
        await ctx.send(f"{user.mention} has no roles to remove!")
        return
    removed_roles[user.id] = roles
    try:
        await user.remove_roles(*roles)
    except Exception:
        pass
    await ctx.send(f"❌ Removed all roles from {user.mention} (stored for recovery).")

@bot.command()
@commands.has_permissions(manage_roles=True)
async def recover(ctx, user: discord.Member):
    if user.id not in removed_roles:
        await ctx.send(f"{user.mention} has no roles stored for recovery!")
        return
    try:
        await user.add_roles(*removed_roles[user.id])
    except Exception:
        pass
    removed_roles.pop(user.id, None)
    await ctx.send(f"✅ Recovered all roles for {user.mention}.")

# =========================
# CASE-BASED moderation
# =========================
@bot.command(name='warn')
@commands.has_permissions(manage_roles=True)
async def warn(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    try:
        case_id = await add_case(ctx.guild.id, member.id, ctx.author.id, "Warn", reason)
    except Exception as e:
        await ctx.send("⚠️ Unable to save case to database. Check bot logs.")
        print("add_case error:", e)
        return

    counts = await get_case_counts(ctx.guild.id, member.id)
    embed = discord.Embed(color=discord.Color.gold(), timestamp=datetime.now(timezone.utc))
    embed.description = f"✅ `Case #{case_id}` {member.mention} has been **warned**.\n\n**Reason:** *{reason}*"
    await ctx.send(embed=embed)
    await log_command(ctx, f"Warned {member} | Case #{case_id} | Reason: {reason}", discord.Color.orange())

@bot.command(name='warnings')
@commands.has_permissions(manage_roles=True)
async def warnings_cmd(ctx, member: discord.Member = None):
    member = member or ctx.author
    try:
        cases = await get_user_cases(ctx.guild.id, member.id)
    except Exception as e:
        await ctx.send("⚠️ Unable to read cases from database.")
        print("get_user_cases error:", e)
        return

    if not cases:
        return await ctx.send(f"✅ {member.mention} has no cases.")
    counts = await get_case_counts(ctx.guild.id, member.id)
    embed = discord.Embed(title=f"📋 Cases for {member}", color=discord.Color.orange(), timestamp=datetime.now(timezone.utc))
    for cid, mod_id, action, reason, ts in cases:
        moderator = ctx.guild.get_member(mod_id)
        mod_name = str(moderator) if moderator else f"<@{mod_id}>"
        # format timestamp
        try:
            ts_display = datetime.fromisoformat(ts).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        except Exception:
            ts_display = str(ts)
        embed.add_field(name=f"Case #{cid} — {action}", value=f"**Moderator:** {mod_name}\n**Reason:** {reason}\n**At:** {ts_display}", inline=False)
    embed.set_footer(text=f"Warned: {counts['Warn']} | Muted: {counts['Mute']} | Kicked: {counts['Kick']} | Banned: {counts['Ban']}")
    await ctx.send(embed=embed)

@bot.command(name='unwarn')
@commands.has_permissions(manage_roles=True)
async def unwarn_cmd(ctx, case_id: int):
    try:
        case = await get_case_by_id(ctx.guild.id, case_id)
    except Exception as e:
        await ctx.send("⚠️ Unable to read cases from database.")
        print("get_case_by_id error:", e)
        return

    if not case:
        return await ctx.send("⚠️ Case not found.")
    cid, guild_id, user_id, mod_id, action, reason, ts = case
    if action != "Warn":
        return await ctx.send("⚠️ That case is not a warn-type case.")
    member = ctx.guild.get_member(user_id)

    embed = discord.Embed(title="⚠️ Confirm Unwarn", color=discord.Color.red(), timestamp=datetime.now(timezone.utc))
    embed.add_field(name="Member", value=f"{member if member else f'<@{user_id}>'}", inline=False)
    embed.add_field(name="Action", value="Warn", inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_footer(text="Reply with yes/no within 30s")

    prompt = await ctx.send(embed=embed)

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() in ("yes", "no")

    try:
        reply = await bot.wait_for('message', check=check, timeout=30.0)
    except asyncio.TimeoutError:
        return await ctx.send("⏳ Confirmation timed out. Action cancelled.")

    if reply.content.lower() == "yes":
        try:
            await remove_case(case_id)
        except Exception as e:
            await ctx.send("⚠️ Unable to remove case from database.")
            print("remove_case error:", e)
            return
        await ctx.send(f"✅ Case #{case_id} for **{member if member else f'<@{user_id}>'}** has been removed.")
        await log_command(ctx, f"Removed case #{case_id} for user {user_id}", discord.Color.green())
    else:
        await ctx.send("❌ Action cancelled.")

# Manual mute tracked as case
@bot.command(name='mute')
@commands.has_permissions(manage_roles=True)
async def mute_cmd(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    mute_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not mute_role:
        return await ctx.send("⚠️ No 'Muted' role found on this server.")
    try:
        await member.add_roles(mute_role)
    except Exception:
        pass
    try:
        case_id = await add_case(ctx.guild.id, member.id, ctx.author.id, "Mute", reason)
    except Exception:
        await ctx.send("⚠️ Unable to save case to database.")
        return
    counts = await get_case_counts(ctx.guild.id, member.id)
    await ctx.send(f"🤐 Muted {member.mention} | Case #{case_id} | Reason: {reason}\nWarned: {counts['Warn']} | Muted: {counts['Mute']} | Kicked: {counts['Kick']} | Banned: {counts['Ban']}")
    await log_command(ctx, f"Muted {member} | Case #{case_id} | Reason: {reason}", discord.Color.orange())

# Kick / Ban (tracked)
@bot.command(name='kick')
@commands.has_permissions(kick_members=True)
async def kick_cmd(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    try:
        await member.kick(reason=reason)
    except Exception:
        pass
    try:
        case_id = await add_case(ctx.guild.id, member.id, ctx.author.id, "Kick", reason)
    except Exception:
        await ctx.send("⚠️ Unable to save case to database.")
        return
    await ctx.send(f"👢 Kicked {member.mention} | Case #{case_id} | Reason: {reason}")
    await log_command(ctx, f"Kicked {member} | Case #{case_id} | Reason: {reason}", discord.Color.red())

@bot.command(name='ban')
@commands.has_permissions(ban_members=True)
async def ban_cmd(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    try:
        await member.ban(reason=reason)
    except Exception:
        pass
    try:
        case_id = await add_case(ctx.guild.id, member.id, ctx.author.id, "Ban", reason)
    except Exception:
        await ctx.send("⚠️ Unable to save case to database.")
        return
    await ctx.send(f"🔨 Banned {member.mention} | Case #{case_id} | Reason: {reason}")
    await log_command(ctx, f"Banned {member} | Case #{case_id} | Reason: {reason}", discord.Color.red())

# =========================
# Utility commands
# =========================
@bot.command(name="clear")
@commands.has_permissions(manage_messages=True)
async def clear_cmd(ctx, amount: int):
    await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"🧹 Cleared {amount} messages.", delete_after=5)
    await log_command(ctx, f"Cleared {amount} messages in {ctx.channel.mention}", discord.Color.purple())

@bot.command(name="purge")
@commands.has_permissions(manage_messages=True)
async def purge_cmd(ctx, amount: int):
    await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"🧽 Purged {amount} messages.", delete_after=5)
    await log_command(ctx, f"Purged {amount} messages in {ctx.channel.mention}", discord.Color.purple())

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

@bot.command()
@commands.has_permissions(manage_roles=True)
async def addrole(ctx, member: discord.Member, role: discord.Role):
    await member.add_roles(role)
    await ctx.send(f"✅ Added <@&{role.id}> to {member.mention}.")

@bot.command()
@commands.has_permissions(manage_roles=True)
async def removerole(ctx, member: discord.Member, role: discord.Role):
    await member.remove_roles(role)
    await ctx.send(f"❌ Removed <@&{role.id}> from {member.mention}.")

# =========================
# Info commands
# =========================
@bot.command()
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author
    roles = " ".join([f"<@&{r.id}>" for r in member.roles if r != ctx.guild.default_role]) or "None"
    embed = discord.Embed(title=f"👤 User Info - {member}", color=discord.Color.blue())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="ID", value=member.id, inline=False)
    embed.add_field(name="Joined Server", value=member.joined_at.strftime("%Y-%m-%d %H:%M:%S"), inline=False)
    embed.add_field(name="Account Created", value=member.created_at.strftime("%Y-%m-%d %H:%M:%S"), inline=False)
    embed.add_field(name="Roles", value=roles, inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def serverinfo(ctx):
    guild = ctx.guild
    embed = discord.Embed(title=f"🌍 Server Info - {guild.name}", color=discord.Color.green())
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    embed.add_field(name="ID", value=guild.id, inline=False)
    embed.add_field(name="Owner", value=guild.owner.mention, inline=False)
    embed.add_field(name="Members", value=guild.member_count, inline=False)
    embed.add_field(name="Created On", value=guild.created_at.strftime("%Y-%m-%d %H:%M:%S"), inline=False)
    await ctx.send(embed=embed)
    
# =========================
# Productivity                                                                
# =========================
afk_users = {}

@bot.command()
async def afk(ctx, *, reason: str = "AFK"):
    """Set yourself as AFK with an optional reason."""
    afk_users[ctx.author.id] = reason
    await ctx.send(f"{ctx.author.mention} is now AFK: {reason}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Agar AFK user wapas message bhejta hai toh unka AFK hata do
    if message.author.id in afk_users:
        del afk_users[message.author.id]
        await message.channel.send(f"Welcome back {message.author.mention}, I removed your AFK.")

    # Agar koi AFK user ko mention kare toh unka reason dikhado
    for mention in message.mentions:
        if mention.id in afk_users:
            reason = afk_users[mention.id]
            await message.channel.send(f"{mention.display_name} is AFK: {reason}")

    await bot.process_commands(message)

# =========================
# Remind
# =========================   
@bot.command()
async def remindme(ctx, time: str, *, reminder: str):
    """Set a reminder. Usage: $remindme 10m Take a break!"""
    unit = time[-1]
    if not time[:-1].isdigit():
        return await ctx.send("Invalid time format! Example: 10s, 5m, 2h")

    duration = int(time[:-1])
    if unit == "s":
        delay = duration
    elif unit == "m":
        delay = duration * 60
    elif unit == "h":
        delay = duration * 3600
    else:
        return await ctx.send("Invalid unit! Use s, m, or h (e.g., 10s, 5m, 1h)")

    await ctx.send(f"Okay {ctx.author.mention}, I’ll remind you in {time}.")

    await asyncio.sleep(delay)
    await ctx.send(f"⏰ Reminder for {ctx.author.mention}: {reminder}")

# =========================
# 💡 Suggestion System (Pro v6.8)
# =========================

SUGGESTION_CHANNEL_ID = 1418641633750159491   # Your suggestion channel
CO_OWNER_ROLE_ID = 1418641632236011665        # Co-Owner role


# =========================
# 📌 Suggest Command
# =========================
@bot.command(name="suggest")
async def suggest(ctx, *, idea: str = None):
    if not idea:
        error_embed = discord.Embed(
            title="⚠️ Missing Suggestion",
            description="You need to provide a suggestion.\n\n**Example:**\n```$suggest Add giveaways```",
            color=discord.Color.red()
        )
        return await ctx.send(embed=error_embed)

    channel = ctx.guild.get_channel(SUGGESTION_CHANNEL_ID)
    if not channel:
        return await ctx.send("❌ Suggestion channel not found! Please contact an admin.")

    # DB Insert
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                message_id INTEGER,
                channel_id INTEGER,
                suggestion TEXT,
                status TEXT DEFAULT 'Pending',
                created_at TIMESTAMP
            )
        """)
        await db.commit()

        cursor = await db.execute("INSERT INTO suggestions (user_id, channel_id, suggestion, created_at) VALUES (?, ?, ?, ?)",
                                  (ctx.author.id, channel.id, idea, datetime.utcnow()))
        await db.commit()
        suggestion_id = cursor.lastrowid

    # Embed
    embed = discord.Embed(
        title=f"💡 Suggestion #{suggestion_id}",
        description=f"```{idea}```",
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="👤 Suggested by", value=ctx.author.mention, inline=True)
    embed.add_field(name="📌 Status", value="⏳ Pending Approval", inline=True)
    embed.set_footer(text="Suggestion System • Pro v6.8")

    msg = await channel.send(embed=embed)
    await msg.add_reaction("👍")
    await msg.add_reaction("👎")

    async with aiosqlite.connect("bot.db") as db:
        await db.execute("UPDATE suggestions SET message_id = ? WHERE id = ?", (msg.id, suggestion_id))
        await db.commit()

    confirm = discord.Embed(
        title="✅ Suggestion Submitted!",
        description=f"Your suggestion has been posted in {channel.mention}.\n\n**ID:** `#{suggestion_id}`\n```{idea}```",
        color=discord.Color.green()
    )
    await ctx.send(embed=confirm)


# =========================
# 🔧 Update Status
# =========================
async def update_status(ctx, suggestion_id: int, status: str, color: discord.Color, emoji: str):
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("SELECT message_id, channel_id, user_id FROM suggestions WHERE id = ?", (suggestion_id,))
        row = await cursor.fetchone()

    if not row:
        return await ctx.send("❌ Suggestion not found.")

    channel = ctx.guild.get_channel(row[1])
    if not channel:
        return await ctx.send("❌ Channel not found.")
    msg = await channel.fetch_message(row[0])

    embed = msg.embeds[0]
    embed.set_field_at(1, name="📌 Status", value=f"{emoji} {status} by {ctx.author.mention}", inline=True)
    embed.color = color
    await msg.edit(embed=embed)

    async with aiosqlite.connect("bot.db") as db:
        await db.execute("UPDATE suggestions SET status = ? WHERE id = ?", (status, suggestion_id))
        await db.commit()

    user = ctx.guild.get_member(row[2])
    if user:
        try:
            await user.send(f"📢 Your suggestion (ID #{suggestion_id}) has been **{status}** by {ctx.author.mention}.")
        except:
            pass

    await ctx.send(f"{emoji} Suggestion #{suggestion_id} marked as **{status}**.")


# =========================
# 🔒 Status Commands (Co-Owners Only)
# =========================
@bot.command(name="suggest-approve")
async def suggest_approve(ctx, suggestion_id: int):
    if CO_OWNER_ROLE_ID not in [r.id for r in ctx.author.roles]:
        return await ctx.send("❌ You don’t have permission.")
    await update_status(ctx, suggestion_id, "Approved", discord.Color.green(), "✅")

@bot.command(name="suggest-deny")
async def suggest_deny(ctx, suggestion_id: int):
    if CO_OWNER_ROLE_ID not in [r.id for r in ctx.author.roles]:
        return await ctx.send("❌ You don’t have permission.")
    await update_status(ctx, suggestion_id, "Denied", discord.Color.red(), "❌")

@bot.command(name="suggest-maybe")
async def suggest_maybe(ctx, suggestion_id: int):
    if CO_OWNER_ROLE_ID not in [r.id for r in ctx.author.roles]:
        return await ctx.send("❌ You don’t have permission.")
    await update_status(ctx, suggestion_id, "Under Review", discord.Color.gold(), "🤔")


# =========================
# 📜 Suggestion List (Paginated)
# =========================
@bot.command(name="suggestlist")
async def suggestlist(ctx, status: str = "Pending"):
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("SELECT id, suggestion, user_id, status FROM suggestions WHERE status = ?", (status,))
        rows = await cursor.fetchall()

    if not rows:
        return await ctx.send(f"❌ No suggestions with status `{status}` found.")

    pages = []
    per_page = 5
    for i in range(0, len(rows), per_page):
        embed = discord.Embed(
            title=f"📋 Suggestions ({status})",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow()
        )
        for row in rows[i:i+per_page]:
            user = ctx.guild.get_member(row[2])
            user_tag = user.mention if user else f"User ID {row[2]}"
            embed.add_field(
                name=f"ID #{row[0]} | By {user_tag}",
                value=f"```{row[1][:500]}```\n📌 Status: **{row[3]}**",
                inline=False
            )
        pages.append(embed)

    class Paginator(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            self.index = 0

        @discord.ui.button(label="⬅️ Prev", style=discord.ButtonStyle.primary)
        async def prev(self, interaction, button):
            if self.index > 0:
                self.index -= 1
                await interaction.response.edit_message(embed=pages[self.index], view=self)

        @discord.ui.button(label="➡️ Next", style=discord.ButtonStyle.primary)
        async def next(self, interaction, button):
            if self.index < len(pages) - 1:
                self.index += 1
                await interaction.response.edit_message(embed=pages[self.index], view=self)

    view = Paginator()
    await ctx.send(embed=pages[0], view=view)

# =======================
# Ghost ping
# =======================
@bot.command(name="ghostpingall", help="Ghost ping everyone to be active.")
@commands.has_permissions(mention_everyone=True)
async def ghostpingall(ctx):
    # Send the ghost ping
    msg = await ctx.send("@everyone Be active!")
    # Delete immediately
    await msg.delete()
    # Optional: temporary confirmation for the command issuer
    await ctx.send("✅ Ghost pinged everyone.", delete_after=5)
    
# =========================
# 📜 Help Command v10.1 (Dropdown Menu + Emojis + Staff Badge)
# =========================

# Role IDs
ROLES = {
    "full_staff": 1418641632148066433,
    "mute_only": 1418641632148066431,
    "kick_mute": 1418641632148066432,
    "rape_recover": [1418641632236011665, 1418641632236011667, 1418641632236011669],
    "trial": 1418641632236011665,
    "antinuke": 1418641632236011669
}

@bot.command()
async def help(ctx):
    user_roles = [r.id for r in ctx.author.roles]

    categories = {}

    # Staff-only: Moderation
    moderation_cmds = []
    if ROLES["full_staff"] in user_roles or ROLES["kick_mute"] in user_roles:
        moderation_cmds.extend([
            "`$ban @user [reason]` - Ban a user",
            "`$kick @user [reason]` - Kick a user"
        ])
    if ROLES["full_staff"] in user_roles or ROLES["mute_only"] in user_roles or ROLES["kick_mute"] in user_roles:
        moderation_cmds.append("`$mute @user [time]` - Mute a user")
    if ROLES["full_staff"] in user_roles:
        moderation_cmds.extend([
            "`$unmute @user` - Unmute a user",
            "`$warn @user [reason]` - Warn a user",
            "`$unwarn <case_id>` - Remove a warning",
            "`$permdemote @user` - Permanent demotion"
        ])
    if any(role in user_roles for role in ROLES["rape_recover"]):
        moderation_cmds.extend([
            "`$rape @user` - Remove all roles",
            "`$recover @user` - Restore removed roles"
        ])
    if ROLES["trial"] in user_roles:
        moderation_cmds.append("`$trial @user` - Add trial staff roles")

    if moderation_cmds:
        categories["🛡️ Moderation (Staff Only)"] = moderation_cmds

    # Utility
    categories["⚙️ Utility"] = [
        "`$userinfo @user` - View info about a user",
        "`$serverinfo` - View server info",
        "`$addrole @user @role` - Add role",
        "`$removerole @user @role` - Remove role",
        "`$purge [amount]` - Delete messages",
        "`$lock` / `$unlock` - Lock or unlock a channel"
    ]

    # Security
    security_cmds = []
    if ROLES["antinuke"] in user_roles:
        security_cmds.extend([
            "`$antinuke` - Enable anti-nuke protection",
            "`$disableantinuke` - Disable anti-nuke protection"
        ])
    if security_cmds:
        categories["🛡️ Security (Staff Only)"] = security_cmds

    # Management
    management_cmds = []
    if ROLES["full_staff"] in user_roles:
        management_cmds.extend([
            "`$setprefix <prefix>` - Change bot prefix",
            "`$settings` - View server settings"
        ])
    if management_cmds:
        categories["📊 Management (Staff Only)"] = management_cmds

    # -----------------
    # Create embeds per category
    # -----------------
    embeds = {}
    for cat, cmds in categories.items():
        embed = discord.Embed(
            title=f"Help — {cat}",
            description="\n".join(cmds),
            color=discord.Color.blurple()
        )
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
        embeds[cat] = embed

    # -----------------
    # Dropdown menu view with emojis
    # -----------------
    class HelpDropdown(View):
        def __init__(self):
            super().__init__(timeout=120)
            options = [
                discord.SelectOption(label=cat, description=f"View {cat} commands", emoji=cat.split(" ")[0])
                for cat in categories.keys()
            ]
            self.select = Select(placeholder="Select a category...", options=options)
            self.select.callback = self.callback
            self.add_item(self.select)

        async def callback(self, interaction: discord.Interaction):
            selected = self.select.values[0]
            await interaction.response.edit_message(embed=embeds[selected], view=self)

    view = HelpDropdown()
    first_category = list(categories.keys())[0]
    await ctx.send(embed=embeds[first_category], view=view)

# =========================
# Run
# =========================
keep_alive()
bot.run(os.getenv('DISCORD_TOKEN'))






























