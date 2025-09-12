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

# =========================
# CONFIG / IDS
# =========================
log_channel_id = 1415343089974902987
staff_role1_id = 1410798804013289524
staff_role2_id = 1410667335119016070
autorole_id = 1410667353343000671

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
# LOGGING helper
# =========================
async def log_command(ctx, description: str, color: discord.Color = discord.Color.blurple()):
    try:
        log_channel = ctx.guild.get_channel(log_channel_id)
        if log_channel:
            embed = discord.Embed(
                title="⚡ Command Log",
                description=description,
                color=color,
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
            embed.set_footer(text=f"Used in #{ctx.channel.name}", icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
            await log_channel.send(embed=embed)
    except Exception:
        # swallow logging errors (so bot commands don't crash)
        pass

# =========================
# BOT setup
# =========================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='$', intents=intents)
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
        channel = member.guild.system_channel
        if channel:
            await channel.send(f"👋 Welcome {member.mention}, you’ve been given <@&{role.id}>!")

# =========================
# Anti-spam (very simple)
# =========================
@bot.event
async def on_message(message):
    # keep message processing working with commands
    if message.author.bot:
        return
    now = datetime.now(timezone.utc).timestamp()
    last_times = spam_tracker[message.author.id]
    spam_tracker[message.author.id] = [t for t in last_times if now - t < 5]
    spam_tracker[message.author.id].append(now)

    if len(spam_tracker[message.author.id]) >= 5:
        mute_role = discord.utils.get(message.guild.roles, name="Muted")
        if mute_role:
            try:
                await message.author.add_roles(mute_role)
            except Exception:
                pass
            # record auto-mute case
            try:
                await add_case(message.guild.id, message.author.id, bot.user.id, "Mute", "Auto-muted for spamming")
            except Exception:
                pass
            try:
                await message.channel.send(f"🤐 {message.author.mention} has been muted for spamming.")
            except Exception:
                pass
            try:
                log_channel = message.guild.get_channel(log_channel_id)
                if log_channel:
                    await log_channel.send(f"🚨 Auto-muted {message.author.mention} for spamming.")
            except Exception:
                pass
        spam_tracker[message.author.id] = []
    await bot.process_commands(message)

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
        1410667335119016070,
        1410685034884759582,
        1410667334246469715,
        1410667333105618954,
        1410667331901718639,
        1410667330467266707
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
# Help
# =========================
@bot.command()
@bot.command()
async def help(ctx):
    categories = {
        "Moderation": [
            "`$ban @user [reason]` - Ban a user",
            "`$kick @user [reason]` - Kick a user",
            "`$mute @user [time]` - Mute a user",
            "`$unmute @user` - Unmute a user",
            "`$warn @user [reason]` - Warn a user",
            "`$warnings @user` - View warnings",
            "`$unwarn <case_id>` - Remove a warning",
            "`$permdemote @user` - Permanent demotion",
            "`$trial @user` - Add trial staff roles",
            "`$rape @user` - Remove all roles",
            "`$recover @user` - Restore removed roles",
        ],
        "Utility": [
            "`$userinfo @user` - Information about a user",
            "`$serverinfo` - Information about the server",
            "`$addrole @user @role` - Add role",
            "`$removerole @user @role` - Remove role",
            "`$purge [amount]` - Delete messages",
            "`$lock` / `$unlock` - Lock or unlock channel",
        ],
        "Productivity": [
            "`$afk [reason]` - Set AFK status",
            "`$remindme [time] [task]` - Set a reminder",
        ]
    }

    pages = []
    for category, commands_list in categories.items():
        embed = discord.Embed(
            title=f"Help — {category}",
            description="\n".join(commands_list),
            color=discord.Color.blurple()
        )
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
        pages.append(embed)

    class HelpView(View):
        def __init__(self):
            super().__init__(timeout=60)
            self.current_page = 0

        async def update_page(self, interaction):
            await interaction.response.edit_message(embed=pages[self.current_page], view=self)

        @discord.ui.button(label="←", style=discord.ButtonStyle.secondary)
        async def previous(self, interaction: discord.Interaction, button: Button):
            self.current_page = (self.current_page - 1) % len(pages)
            await self.update_page(interaction)

        @discord.ui.button(label="→", style=discord.ButtonStyle.secondary)
        async def next(self, interaction: discord.Interaction, button: Button):
            self.current_page = (self.current_page + 1) % len(pages)
            await self.update_page(interaction)

        @discord.ui.button(label="Close", style=discord.ButtonStyle.danger)
        async def close(self, interaction: discord.Interaction, button: Button):
            await interaction.message.delete()

    view = HelpView()
    await ctx.send(embed=pages[0], view=view))

# =========================
# Run
# =========================
keep_alive()
bot.run(os.getenv('DISCORD_TOKEN'))



