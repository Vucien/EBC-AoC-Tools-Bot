import logging
import asyncio
import os
from datetime import datetime, timedelta, timezone
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

# Load environment variables from token.env file
load_dotenv('token.env')

# Import character registry module
try:
    from character_registry import setup_character_registry
    CHARACTER_REGISTRY_AVAILABLE = True
    print("✅ Character registry module imported successfully")
except ImportError as e:
    CHARACTER_REGISTRY_AVAILABLE = False
    print(f"⚠️ Character registry module not found: {e}")
    print("   Make sure character_registry.py is in the same folder!")

# Debug: Check if .env file exists
import pathlib
env_file = pathlib.Path('token.env')
if env_file.exists():
    print(f"✅ Found token.env at: {env_file.absolute()}")
else:
    print(f"❌ token.env not found at: {env_file.absolute()}")
    print(f"📁 Current working directory: {pathlib.Path.cwd()}")

# =========================
# COG LOADING
# =========================

async def load_cogs():
    """Load additional cogs"""
    try:
        await bot.load_extension('cogs.artisan_economy')
        logger.info("✅ Loaded artisan_economy cog")
    except Exception as e:
        logger.error(f"❌ Failed to load artisan_economy cog: {e}")
        import traceback
        traceback.print_exc()

# =========================
# CONFIG – EDIT THESE
# =========================

# Category where MEE6 creates the TEMP VOICE channels
TEMP_VOICE_CATEGORY_ID = 1444964139209457685

# Channel where waitlist recruitment broadcasts are sent
BROADCAST_CHANNEL_ID = 1444137487839662120

# Max group size
GROUP_SIZE = 8

# Maximum queue size per channel
MAX_QUEUE_SIZE = 50

# Allowed classes
ALLOWED_CLASSES = [
    "Tank", "Cleric", "Bard", "Summoner",
    "Mage", "Ranger", "Rogue", "Fighter"
]

# CLASS → EMOJI MAP
CLASS_EMOJIS = {
    "Tank": "<:tank:1444981981929537636>",
    "Cleric": "<:cleric:1444982092135141478>",
    "Bard": "<:bard:1444981426310090762>",
    "Summoner": "<:summoner:1444981951806312489>",
    "Mage": "<:mage:1444982031183380562>",
    "Ranger": "<:ranger:1444981901495373966>",
    "Rogue": "<:rogue:1444981927013646381>",
    "Fighter": "<:fighter:1444982132081426502>",
}

# =========================
# LOGGING
# =========================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =========================
# BOT SETUP
# =========================

intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Data structures
queues: dict[int, list[dict]] = {}
queue_messages: dict[int, int] = {}
queue_hosts: dict[int, int] = {}
group_info: dict[int, dict[str, str]] = {}
notified_next: dict[int, int] = {}
broadcast_messages: dict[int, list[int]] = {}
queue_locks: dict[int, asyncio.Lock] = {}
queue_last_active: dict[int, datetime] = {}

# =========================
# HELPER FUNCTIONS
# =========================

def normalise_class_name(name: str) -> str | None:
    name = name.strip().lower()
    for c in ALLOWED_CLASSES:
        if c.lower() == name:
            return c
    return None

def validate_level(level_str: str) -> tuple[bool, str]:
    level_str = level_str.strip()
    if not level_str.isdigit():
        return False, "Level must be a number."
    level = int(level_str)
    if level < 1 or level > 9999:
        return False, "Level must be between 1 and 9999."
    return True, str(level)

async def get_or_create_lock(channel_id: int) -> asyncio.Lock:
    if channel_id not in queue_locks:
        queue_locks[channel_id] = asyncio.Lock()
    return queue_locks[channel_id]

def build_queue_embed(channel: discord.VoiceChannel) -> discord.Embed:
    entries = queues.get(channel.id, [])
    host_id = queue_hosts.get(channel.id)
    info = group_info.get(channel.id, {})

    title = f"Queue for {channel.name}"
    desc_lines: list[str] = []

    if host_id:
        desc_lines.append(f"**Host:** <@{host_id}>")
    else:
        desc_lines.append("**Host:** Not set")

    min_level = info.get("min_level", "").strip()
    max_level = info.get("max_level", "").strip()
    desc_text = info.get("description", "").strip()

    if min_level or max_level or desc_text:
        desc_lines.append("\n**Group Info:**")
        if min_level:
            desc_lines.append(f"- Minimum Level: {min_level}")
        if max_level:
            desc_lines.append(f"- Maximum Level: {max_level}")
        if desc_text:
            desc_lines.append(f"- Description: {desc_text}")

    if not entries:
        desc_lines.append("\n_No one is in the queue yet. Use **Join** to add yourself._")
    else:
        desc_lines.append("\n**Queued Members:**")
        for i, entry in enumerate(entries, start=1):
            clazz = entry['class']
            emoji = CLASS_EMOJIS.get(clazz, "")
            desc_lines.append(
                f"{i}. {emoji} <@{entry['user_id']}> – {clazz} (Lv {entry['level']})"
            )

    desc_lines.append(f"\n**Current Queue Size:** {len(entries)}/{MAX_QUEUE_SIZE}")
    desc_lines.append(f"**Group Size:** {GROUP_SIZE} players")
    
    embed = discord.Embed(
        title=title,
        description="\n".join(desc_lines),
        colour=discord.Colour.blurple()
    )
    embed.set_footer(text="Use the buttons below to manage the queue.")
    return embed

async def rename_channel_initial(channel: discord.VoiceChannel):
    if not channel.category:
        return

    voice_channels = [
        ch for ch in channel.category.channels
        if isinstance(ch, discord.VoiceChannel)
    ]
    voice_channels.sort(key=lambda ch: ch.position)

    try:
        index = voice_channels.index(channel) + 1
    except ValueError:
        index = 1

    new_name = f"{index} - Waitlist Active VC Chat"

    if channel.name == new_name:
        return

    try:
        await channel.edit(name=new_name)
        logger.info(f"Renamed channel {channel.id} to '{new_name}'")
    except Exception as e:
        logger.warning(f"Failed to rename channel {channel.id}: {e}")

async def notify_next_in_queue(channel: discord.VoiceChannel):
    entries = queues.get(channel.id, [])

    if not entries:
        notified_next.pop(channel.id, None)
        return

    first_user_id = entries[0]["user_id"]
    last_notified = notified_next.get(channel.id)

    if last_notified == first_user_id:
        return

    member = channel.guild.get_member(first_user_id)
    if member is None:
        lock = await get_or_create_lock(channel.id)
        async with lock:
            entries = queues.get(channel.id, [])
            entries = [e for e in entries if e["user_id"] != first_user_id]
            queues[channel.id] = entries
        await notify_next_in_queue(channel)
        return

    try:
        dm = await member.create_dm()
        await dm.send(
            f"🎮 You are now **next in queue** for the group in **{channel.name}**.\n"
            "Please be ready to join when the host pulls you into the group."
        )
        logger.info(f"Notified {member.id} that they are next in queue for {channel.id}")
    except discord.Forbidden:
        pass
    except Exception as e:
        logger.warning(f"Failed to DM user {member.id}: {e}")

    notified_next[channel.id] = first_user_id

async def update_queue_message(channel: discord.VoiceChannel):
    if channel.id not in queue_messages:
        return

    msg_id = queue_messages[channel.id]
    try:
        msg = await channel.fetch_message(msg_id)
    except discord.NotFound:
        logger.warning(f"Queue message {msg_id} not found for channel {channel.id}")
        queue_messages.pop(channel.id, None)
        return

    embed = build_queue_embed(channel)
    view = QueueView(channel.id)
    
    try:
        await msg.edit(embed=embed, view=view)
        queue_last_active[channel.id] = datetime.now(timezone.utc)
    except Exception as e:
        logger.error(f"Failed to update queue message: {e}")

    await notify_next_in_queue(channel)

async def reassign_host_if_needed(channel: discord.VoiceChannel):
    host_id = queue_hosts.get(channel.id)
    if host_id is None:
        return
    
    host_member = channel.guild.get_member(host_id)
    if host_member is not None:
        return
    
    logger.info(f"Host {host_id} left server, reassigning for channel {channel.id}")
    
    if channel.members:
        new_host = channel.members[0]
        queue_hosts[channel.id] = new_host.id
        logger.info(f"Assigned new host {new_host.id} for channel {channel.id}")
        
        try:
            dm = await new_host.create_dm()
            await dm.send(
                f"🎮 You have been automatically assigned as the **host** for the waitlist in **{channel.name}** "
                f"because the previous host left the server."
            )
        except discord.Forbidden:
            pass
        
        await update_queue_message(channel)
    else:
        queue_hosts.pop(channel.id, None)
        logger.info(f"No members in channel {channel.id}, cleared host")
        await update_queue_message(channel)

async def cleanup_inactive_queues():
    current_time = datetime.now(timezone.utc)
    channels_to_remove = []
    
    for channel_id in list(queues.keys()):
        channel = bot.get_channel(channel_id)
        
        if channel is None:
            channels_to_remove.append(channel_id)
            continue
        
        last_active = queue_last_active.get(channel_id)
        if last_active and (current_time - last_active) > timedelta(days=7):
            channels_to_remove.append(channel_id)
            logger.info(f"Removing inactive queue for channel {channel_id}")
    
    for channel_id in channels_to_remove:
        queues.pop(channel_id, None)
        queue_messages.pop(channel_id, None)
        queue_hosts.pop(channel_id, None)
        notified_next.pop(channel_id, None)
        group_info.pop(channel_id, None)
        queue_locks.pop(channel_id, None)
        queue_last_active.pop(channel_id, None)
        broadcast_messages.pop(channel_id, None)
    
    if channels_to_remove:
        logger.info(f"Cleaned up {len(channels_to_remove)} inactive queues")

async def cleanup_orphaned_broadcasts():
    for guild in bot.guilds:
        broadcast_channel = guild.get_channel(BROADCAST_CHANNEL_ID)
        if not isinstance(broadcast_channel, discord.TextChannel):
            continue
        
        try:
            messages = []
            async for message in broadcast_channel.history(limit=100):
                if message.author == bot.user and message.embeds:
                    messages.append(message)
            
            deleted_count = 0
            for message in messages:
                if not message.components:
                    continue
                
                should_delete = False
                
                for vc_id, msg_ids in list(broadcast_messages.items()):
                    if message.id in msg_ids:
                        vc = guild.get_channel(vc_id)
                        if vc is None or vc_id not in queues:
                            should_delete = True
                            msg_ids.remove(message.id)
                            if not msg_ids:
                                broadcast_messages.pop(vc_id, None)
                        break
                
                if not should_delete and message.embeds:
                    embed = message.embeds[0]
                    if embed.description:
                        import re
                        channel_mentions = re.findall(r'<#(\d+)>', embed.description)
                        if channel_mentions:
                            vc_id = int(channel_mentions[0])
                            vc = guild.get_channel(vc_id)
                            if vc is None or vc_id not in queues:
                                should_delete = True
                
                if should_delete:
                    try:
                        await message.delete()
                        deleted_count += 1
                        logger.info(f"Deleted orphaned broadcast message {message.id}")
                    except discord.NotFound:
                        pass
                    except Exception as e:
                        logger.warning(f"Failed to delete orphaned broadcast {message.id}: {e}")
            
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} orphaned broadcast messages in {guild.name}")
                
        except discord.Forbidden:
            logger.warning(f"Missing permissions to read message history in broadcast channel")
        except Exception as e:
            logger.error(f"Error during broadcast cleanup: {e}")

# =========================
# BACKGROUND TASKS
# =========================

@tasks.loop(hours=1)
async def periodic_cleanup():
    await cleanup_inactive_queues()
    await cleanup_orphaned_broadcasts()
    await refresh_all_queue_embeds()

@tasks.loop(minutes=5)
async def check_hosts():
    for channel_id in list(queue_hosts.keys()):
        channel = bot.get_channel(channel_id)
        if isinstance(channel, discord.VoiceChannel):
            await reassign_host_if_needed(channel)

@tasks.loop(hours=6)
async def cleanup_broadcasts():
    await cleanup_orphaned_broadcasts()

# =========================
# MODALS
# =========================

class GroupInfoModal(discord.ui.Modal, title="Edit Group Info"):
    def __init__(self, channel_id: int):
        super().__init__()
        self.channel_id = channel_id

        self.min_level = discord.ui.TextInput(
            label="Minimum Level",
            placeholder="e.g. 45 (leave blank for none)",
            required=False,
            max_length=10,
        )
        self.max_level = discord.ui.TextInput(
            label="Maximum Level",
            placeholder="e.g. 60 (leave blank for none)",
            required=False,
            max_length=10,
        )
        self.description = discord.ui.TextInput(
            label="Description",
            placeholder="Any notes about this group (role needs, dungeon, rules, etc.)",
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=300,
        )

        self.add_item(self.min_level)
        self.add_item(self.max_level)
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        min_val = str(self.min_level.value).strip()
        max_val = str(self.max_level.value).strip()
        
        if min_val and not min_val.isdigit():
            await interaction.followup.send(
                "❌ Minimum level must be a number.",
                ephemeral=True
            )
            return
        
        if max_val and not max_val.isdigit():
            await interaction.followup.send(
                "❌ Maximum level must be a number.",
                ephemeral=True
            )
            return
        
        info = {
            "min_level": min_val,
            "max_level": max_val,
            "description": str(self.description.value).strip(),
        }
        group_info[self.channel_id] = info

        channel = interaction.guild.get_channel(self.channel_id)
        if isinstance(channel, discord.VoiceChannel):
            await update_queue_message(channel)

        await interaction.followup.send(
            "✅ Group info has been updated.",
            ephemeral=True
        )

class JoinQueueModal(discord.ui.Modal, title="Join Queue"):
    def __init__(self, channel_id: int):
        super().__init__()
        self.channel_id = channel_id

        self.class_input = discord.ui.TextInput(
            label="Class",
            placeholder="Tank, Cleric, Bard, Summoner, Mage, Ranger, Rogue, Fighter",
            required=True,
            max_length=20,
        )
        self.level_input = discord.ui.TextInput(
            label="Level",
            placeholder="Enter your level (e.g. 45)",
            required=True,
            max_length=5,
        )

        self.add_item(self.class_input)
        self.add_item(self.level_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        clazz_raw = str(self.class_input.value)
        level_raw = str(self.level_input.value).strip()

        clazz = normalise_class_name(clazz_raw)
        if clazz is None:
            await interaction.followup.send(
                f"❌ Invalid class. Please use one of: {', '.join(ALLOWED_CLASSES)}",
                ephemeral=True
            )
            return

        is_valid, result = validate_level(level_raw)
        if not is_valid:
            await interaction.followup.send(
                f"❌ {result}",
                ephemeral=True
            )
            return
        
        level_raw = result

        channel_id = self.channel_id
        user_id = interaction.user.id

        lock = await get_or_create_lock(channel_id)
        async with lock:
            entries = queues.setdefault(channel_id, [])
            
            is_already_in_queue = any(e["user_id"] == user_id for e in entries)
            if not is_already_in_queue and len(entries) >= MAX_QUEUE_SIZE:
                await interaction.followup.send(
                    f"❌ The queue is full ({MAX_QUEUE_SIZE}/{MAX_QUEUE_SIZE}). Please wait for a spot to open up.",
                    ephemeral=True
                )
                return

            updated = False
            for entry in entries:
                if entry["user_id"] == user_id:
                    entry["class"] = clazz
                    entry["level"] = level_raw
                    updated = True
                    break
            
            if not updated:
                entries.append({
                    "user_id": user_id,
                    "class": clazz,
                    "level": level_raw
                })

            queues[channel_id] = entries
            position = next(i for i, e in enumerate(entries, 1) if e["user_id"] == user_id)

        channel = interaction.guild.get_channel(channel_id)
        queue_embed = None
        if isinstance(channel, discord.VoiceChannel):
            await update_queue_message(channel)
            queue_embed = build_queue_embed(channel)

        action = "updated your position in" if updated else "joined"
        content = f"✅ You {action} the queue as **{clazz} (Lv {level_raw})** — Position: **#{position}**"

        if queue_embed:
            await interaction.followup.send(
                content=content,
                embed=queue_embed,
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                content=content,
                ephemeral=True
            )

# =========================
# VIEWS & SELECTS
# =========================

class ConfirmRemoveView(discord.ui.View):
    def __init__(self, channel_id: int, user_id: int, timeout: float | None = 60):
        super().__init__(timeout=timeout)
        self.channel_id = channel_id
        self.user_id = user_id

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.danger)
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if guild is None:
            await interaction.response.edit_message(
                content="❌ Something went wrong: no guild found.",
                embed=None,
                view=None
            )
            return

        lock = await get_or_create_lock(self.channel_id)
        async with lock:
            entries = queues.get(self.channel_id, [])
            new_entries = [e for e in entries if e["user_id"] != self.user_id]
            queues[self.channel_id] = new_entries

        channel = guild.get_channel(self.channel_id)
        if isinstance(channel, discord.VoiceChannel):
            try:
                await update_queue_message(channel)
            except Exception as e:
                logger.error(f"Error updating queue message: {e}")

        member = guild.get_member(self.user_id)
        name = member.mention if member else "that user"

        await interaction.response.edit_message(
            content=f"✅ {name} has been removed from the queue.",
            embed=None,
            view=None
        )

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        member = guild.get_member(self.user_id) if guild else None
        name = member.mention if member else "that user"

        await interaction.response.edit_message(
            content=f"ℹ️ {name} was **kept** in the queue.",
            embed=None,
            view=None
        )

class PullSelect(discord.ui.Select):
    def __init__(self, channel_id: int):
        self.channel_id = channel_id

        entries = queues.get(channel_id, [])
        options: list[discord.SelectOption] = []

        channel = bot.get_channel(channel_id)
        guild = channel.guild if isinstance(channel, discord.VoiceChannel) else None

        for entry in entries[:25]:
            user_id = entry["user_id"]
            clazz = entry["class"]
            level = entry["level"]

            member = guild.get_member(user_id) if guild else None
            username = member.display_name if member else f"User {user_id}"

            label = f"{username} – {clazz} (Lv {level})"

            options.append(
                discord.SelectOption(
                    label=label,
                    description=username,
                    value=str(user_id)
                )
            )

        if not options:
            options.append(
                discord.SelectOption(
                    label="Queue is empty",
                    description="No one is currently queued.",
                    value="none",
                    default=True
                )
            )

        super().__init__(
            placeholder="Select a member to pull into your voice channel",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if self.values[0] == "none":
            await interaction.followup.send(
                "ℹ️ There is no one in the queue to pull.",
                ephemeral=True
            )
            return

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send(
                "❌ Something went wrong: no guild found.",
                ephemeral=True
            )
            return

        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.followup.send(
                "❌ You must be in a voice channel to pull someone.",
                ephemeral=True
            )
            return

        voice_channel = interaction.user.voice.channel
        user_id = int(self.values[0])
        member = guild.get_member(user_id)

        if member is None:
            await interaction.followup.send(
                "❌ Could not find that member.",
                ephemeral=True
            )
            return

        try:
            await member.move_to(voice_channel)
        except discord.Forbidden:
            await interaction.followup.send(
                "⚠️ I don't have permission to move that member.",
                ephemeral=True
            )
            return
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"⚠️ Failed to move member: {e}",
                ephemeral=True
            )
            return

        try:
            dm = await member.create_dm()
            await dm.send(
                f"🎮 You have been **pulled into a group** by {interaction.user.mention} "
                f"in **{voice_channel.name}**."
            )
        except discord.Forbidden:
            pass

        embed = discord.Embed(
            title="Remove from Queue?",
            description=(
                f"{member.mention} has been moved to {voice_channel.mention}.\n\n"
                f"Do you also want to **remove them from the queue** for this channel?"
            ),
            colour=discord.Colour.orange()
        )
        view = ConfirmRemoveView(self.channel_id, user_id)

        await interaction.edit_original_response(
            content=None,
            embed=embed,
            view=view
        )

class HostSelect(discord.ui.Select):
    def __init__(self, channel: discord.VoiceChannel):
        self.channel_id = channel.id

        options: list[discord.SelectOption] = []

        for member in channel.members[:25]:
            label = member.display_name
            options.append(
                discord.SelectOption(
                    label=label,
                    description=str(member),
                    value=str(member.id)
                )
            )

        if not options:
            options.append(
                discord.SelectOption(
                    label="No members in voice channel",
                    description="Join the channel first.",
                    value="none",
                    default=True
                )
            )

        super().__init__(
            placeholder="Select a member to set as the new host",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.edit_message(
                content="ℹ️ There are no members in the voice channel to set as host.",
                view=None
            )
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.edit_message(
                content="❌ Something went wrong: no guild found.",
                view=None
            )
            return

        new_host_id = int(self.values[0])
        member = guild.get_member(new_host_id)

        if member is None:
            await interaction.response.edit_message(
                content="❌ Could not find that member.",
                view=None
            )
            return

        queue_hosts[self.channel_id] = new_host_id

        channel = guild.get_channel(self.channel_id)
        if isinstance(channel, discord.VoiceChannel):
            await update_queue_message(channel)

        await interaction.response.edit_message(
            content=f"✅ Host has been changed to {member.mention}.",
            embed=None,
            view=None
        )

class ChangeHostView(discord.ui.View):
    def __init__(self, channel: discord.VoiceChannel, timeout: float | None = 60):
        super().__init__(timeout=timeout)
        self.add_item(HostSelect(channel))

class BroadcastClassSelect(discord.ui.Select):
    def __init__(self, vc_channel: discord.VoiceChannel):
        self.vc_channel_id = vc_channel.id

        options: list[discord.SelectOption] = []

        options.append(
            discord.SelectOption(
                label="Any Classes",
                description="No specific roles required",
                value="any"
            )
        )

        for clazz in ALLOWED_CLASSES:
            options.append(
                discord.SelectOption(
                    label=clazz,
                    description=f"Looking for {clazz}",
                    value=clazz
                )
            )

        super().__init__(
            placeholder="Select classes needed (or Any Classes)",
            options=options,
            min_values=1,
            max_values=len(options)
        )

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.edit_message(
                content="❌ Something went wrong: no guild found.",
                view=None
            )
            return

        vc_channel = guild.get_channel(self.vc_channel_id)
        if not isinstance(vc_channel, discord.VoiceChannel):
            await interaction.response.edit_message(
                content="❌ Could not find the associated voice channel.",
                view=None
            )
            return

        broadcast_channel = guild.get_channel(BROADCAST_CHANNEL_ID)
        if not isinstance(broadcast_channel, discord.TextChannel):
            await interaction.response.edit_message(
                content="❌ Broadcast channel not found or is not a text channel.",
                view=None
            )
            return

        # CRITICAL: Delete old broadcasts from THIS queue BEFORE posting new one
        deleted_count = 0
        logger.info(f"🔍 Checking for old broadcasts from queue {self.vc_channel_id}")
        logger.info(f"📊 Current broadcast_messages dict: {broadcast_messages}")
        
        if self.vc_channel_id in broadcast_messages:
            old_broadcast_ids = broadcast_messages[self.vc_channel_id].copy()
            logger.info(f"🗑️ Found {len(old_broadcast_ids)} old broadcast(s) to delete: {old_broadcast_ids}")
            
            for msg_id in old_broadcast_ids:
                try:
                    old_msg = await broadcast_channel.fetch_message(msg_id)
                    await old_msg.delete()
                    deleted_count += 1
                    logger.info(f"✅ Successfully deleted old broadcast {msg_id}")
                except discord.NotFound:
                    logger.warning(f"⚠️ Broadcast {msg_id} not found (already deleted)")
                except Exception as e:
                    logger.error(f"❌ Failed to delete broadcast {msg_id}: {e}")
            
            logger.info(f"🧹 Cleared {deleted_count} old broadcast(s) for queue {self.vc_channel_id}")
        else:
            logger.info(f"📭 No previous broadcasts found for queue {self.vc_channel_id}")

        values = self.values

        if "any" in values:
            classes_text = "Any Classes"
        else:
            pretty_classes: list[str] = []
            for v in values:
                emoji = CLASS_EMOJIS.get(v, "")
                if emoji:
                    pretty_classes.append(f"{emoji} {v}")
                else:
                    pretty_classes.append(v)
            classes_text = ", ".join(pretty_classes) if pretty_classes else "Any Classes"

        info = group_info.get(vc_channel.id, {})
        min_level = info.get("min_level", "").strip()
        max_level = info.get("max_level", "").strip()
        desc_text = info.get("description", "").strip()

        min_display = min_level if min_level else "Any"
        max_display = max_level if max_level else "Any"

        embed_desc_lines = [
            f"**Waitlist currently active in {vc_channel.mention}.**",
            "",
            "If you meet the requirements, please sign up in that channel's waitlist.",
            "",
            f"**Classes Needed:** {classes_text}",
            f"**Levels:** {min_display} - {max_display}",
        ]

        if desc_text:
            embed_desc_lines.append("")
            embed_desc_lines.append(desc_text)

        embed = discord.Embed(
            title="Waitlist Active",
            description="\n".join(embed_desc_lines),
            colour=discord.Colour.gold()
        )

        msg = await broadcast_channel.send(
            embed=embed,
            view=BroadcastJoinView(vc_channel.id)
        )

        # REPLACE the list with only the new message ID
        broadcast_messages[self.vc_channel_id] = [msg.id]
        logger.info(f"✅ Posted new broadcast {msg.id} for queue {self.vc_channel_id}")
        logger.info(f"📊 Updated broadcast_messages dict: {broadcast_messages}")

        response_text = f"✅ Broadcast sent to {broadcast_channel.mention}."
        if deleted_count > 0:
            response_text += f" Removed {deleted_count} old broadcast(s) from this queue."

        await interaction.response.edit_message(
            content=response_text,
            embed=None,
            view=None
        )

class BroadcastWaitlistView(discord.ui.View):
    def __init__(self, vc_channel: discord.VoiceChannel, timeout: float | None = 60):
        super().__init__(timeout=timeout)
        self.add_item(BroadcastClassSelect(vc_channel))

class BroadcastJoinView(discord.ui.View):
    def __init__(self, vc_channel_id: int, timeout: float | None = None):
        super().__init__(timeout=timeout)
        self.vc_channel_id = vc_channel_id

    @discord.ui.button(label="Join Waitlist", style=discord.ButtonStyle.success)
    async def join_waitlist(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = JoinQueueModal(self.vc_channel_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Leave Waitlist", style=discord.ButtonStyle.danger)
    async def leave_waitlist(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Something went wrong: no guild found.",
                ephemeral=True
            )
            return

        channel = guild.get_channel(self.vc_channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            await interaction.response.send_message(
                "❌ The associated voice channel no longer exists.",
                ephemeral=True
            )
            return

        lock = await get_or_create_lock(self.vc_channel_id)
        async with lock:
            entries = queues.get(self.vc_channel_id, [])
            before = len(entries)
            entries = [e for e in entries if e["user_id"] != interaction.user.id]
            queues[self.vc_channel_id] = entries

        if len(entries) < before:
            msg = "✅ You have been removed from the waitlist."
        else:
            msg = "ℹ️ You were not on this waitlist."

        await update_queue_message(channel)

        queue_embed = build_queue_embed(channel)
        await interaction.response.send_message(
            content=msg,
            embed=queue_embed,
            ephemeral=True
        )

    @discord.ui.button(label="Check Waitlist", style=discord.ButtonStyle.secondary)
    async def check_waitlist(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Something went wrong: no guild found.",
                ephemeral=True
            )
            return

        channel = guild.get_channel(self.vc_channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            await interaction.response.send_message(
                "❌ The associated voice channel no longer exists.",
                ephemeral=True
            )
            return

        queue_embed = build_queue_embed(channel)
        await interaction.response.send_message(
            content=f"📋 Here is the current waitlist for {channel.mention}:",
            embed=queue_embed,
            ephemeral=True
        )

class PullView(discord.ui.View):
    def __init__(self, channel_id: int, timeout: float | None = 60):
        super().__init__(timeout=timeout)
        self.add_item(PullSelect(channel_id))

class QueueView(discord.ui.View):
    def __init__(self, channel_id: int, timeout: float | None = 86400):
        super().__init__(timeout=timeout)
        self.channel_id = channel_id

    @discord.ui.button(label="Join", style=discord.ButtonStyle.success)
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = JoinQueueModal(self.channel_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Leave", style=discord.ButtonStyle.danger)
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel_id = self.channel_id
        user_id = interaction.user.id

        lock = await get_or_create_lock(channel_id)
        async with lock:
            entries = queues.get(channel_id, [])
            before = len(entries)
            entries = [e for e in entries if e["user_id"] != user_id]
            queues[channel_id] = entries

        if len(entries) < before:
            msg = "✅ You have been removed from the queue."
        else:
            msg = "ℹ️ You were not in the queue."

        await interaction.response.send_message(msg, ephemeral=True)

        channel = interaction.guild.get_channel(channel_id)
        if isinstance(channel, discord.VoiceChannel):
            await update_queue_message(channel)

    @discord.ui.button(label="Group Info", style=discord.ButtonStyle.secondary)
    async def group_info_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        host_id = queue_hosts.get(self.channel_id)
        if host_id is not None and interaction.user.id != host_id:
            await interaction.response.send_message(
                "❌ Only the host who started this queue can edit group info.",
                ephemeral=True
            )
            return

        modal = GroupInfoModal(self.channel_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Change Host", style=discord.ButtonStyle.secondary)
    async def change_host_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        host_id = queue_hosts.get(self.channel_id)
        if host_id is not None and interaction.user.id != host_id:
            await interaction.response.send_message(
                "❌ Only the current host can change host.",
                ephemeral=True
            )
            return

        channel = interaction.guild.get_channel(self.channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            await interaction.response.send_message(
                "❌ Something went wrong: this is not a voice channel.",
                ephemeral=True
            )
            return

        view = ChangeHostView(channel)
        await interaction.response.send_message(
            "Select a member in this voice channel to set as the new host:",
            view=view,
            ephemeral=True
        )

    @discord.ui.button(label="Broadcast Waitlist", style=discord.ButtonStyle.secondary)
    async def broadcast_waitlist_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        host_id = queue_hosts.get(self.channel_id)
        if host_id is not None and interaction.user.id != host_id:
            await interaction.response.send_message(
                "❌ Only the current host can broadcast the waitlist.",
                ephemeral=True
            )
            return

        channel = interaction.guild.get_channel(self.channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            await interaction.response.send_message(
                "❌ Something went wrong: this is not a voice channel.",
                ephemeral=True
            )
            return

        view = BroadcastWaitlistView(channel)
        await interaction.response.send_message(
            "Select which classes you are looking for (or **Any Classes**) and I will post a recruitment embed.",
            view=view,
            ephemeral=True
        )

    @discord.ui.button(label="Pull", style=discord.ButtonStyle.primary)
    async def pull_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        host_id = queue_hosts.get(self.channel_id)
        if host_id is not None and interaction.user.id != host_id:
            await interaction.response.send_message(
                "❌ Only the host who started this queue can pull members.",
                ephemeral=True
            )
            return

        entries = queues.get(self.channel_id, [])
        if not entries:
            await interaction.response.send_message(
                "ℹ️ The queue is currently empty.",
                ephemeral=True
            )
            return

        view = PullView(self.channel_id)
        await interaction.response.send_message(
            "Select a member to pull into your current voice channel:",
            view=view,
            ephemeral=True
        )

class StartQueueView(discord.ui.View):
    def __init__(self, channel: discord.VoiceChannel, timeout: float | None = 300):
        super().__init__(timeout=timeout)
        self.channel = channel

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        queue_hosts[self.channel.id] = interaction.user.id
        queues.setdefault(self.channel.id, [])
        queue_last_active[self.channel.id] = datetime.now(timezone.utc)

        embed = build_queue_embed(self.channel)
        view = QueueView(self.channel.id)

        await interaction.response.edit_message(embed=embed, view=view)
        queue_messages[self.channel.id] = interaction.message.id

        await rename_channel_initial(self.channel)

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="❌ Queue was not created for this channel.",
            view=self
        )

# =========================
# AUTOMATIC QUEUE EMBED REFRESH
# =========================

async def refresh_all_queue_embeds():
    """Automatically scan and refresh all 'Create a Queue?' embeds in the temp voice category"""
    
    logger.info("Starting automatic queue embed refresh...")
    
    # Wait for bot to be fully ready
    await bot.wait_until_ready()
    
    # Get all guilds the bot is in
    for guild in bot.guilds:
        category = guild.get_channel(TEMP_VOICE_CATEGORY_ID)
        if not category:
            continue
        
        refreshed = 0
        channels_checked = 0
        
        for channel in category.channels:
            if not isinstance(channel, discord.VoiceChannel):
                continue
                
            channels_checked += 1
            
            try:
                # Search through recent messages in the voice channel
                async for message in channel.history(limit=50):
                    # Check if it's from the bot and has an embed
                    if message.author != bot.user or not message.embeds:
                        continue
                    
                    embed = message.embeds[0]
                    
                    # Check if it's the "Create a Queue?" embed
                    if embed.title == "Create a Queue?":
                        # Create a fresh view and edit the message
                        fresh_view = StartQueueView(channel)
                        await message.edit(view=fresh_view)
                        refreshed += 1
                        logger.info(f"Refreshed 'Create a Queue?' embed in {channel.name} (ID: {channel.id})")
                        break  # Only refresh the first matching embed per channel
                        
            except discord.Forbidden:
                logger.warning(f"No permission to access channel {channel.name} (ID: {channel.id})")
            except Exception as e:
                logger.error(f"Error refreshing embed in {channel.name}: {e}")
        
        if refreshed > 0:
            logger.info(f"✅ Queue embed refresh complete: {refreshed} embeds refreshed across {channels_checked} channels")
        else:
            logger.info(f"No queue embeds found to refresh (checked {channels_checked} channels)")

# =========================
# EVENTS
# =========================

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info("Bot is ready!")
    
    if CHARACTER_REGISTRY_AVAILABLE:
        setup_character_registry(bot)
    else:
        logger.warning("Character registry module not loaded - skipping")
        
    await load_cogs()
    
    try:
        synced = await bot.tree.sync()
        logger.info(f"✅ Synced {len(synced)} slash command(s)")
        for cmd in synced:
            logger.info(f"  - /{cmd.name}")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}")
    
    logger.info("Running initial broadcast cleanup...")
    await cleanup_orphaned_broadcasts()
    
    logger.info("Refreshing queue embeds...")
    await refresh_all_queue_embeds()
    
    if not periodic_cleanup.is_running():
        periodic_cleanup.start()
    if not check_hosts.is_running():
        check_hosts.start()
    if not cleanup_broadcasts.is_running():
        cleanup_broadcasts.start()

@bot.event
async def on_guild_channel_create(channel: discord.abc.GuildChannel):
    if not isinstance(channel, discord.VoiceChannel):
        return

    if not channel.category or channel.category.id != TEMP_VOICE_CATEGORY_ID:
        return

    embed = discord.Embed(
        title="Create a Queue?",
        description=(
            "This looks like a new group voice channel.\n\n"
            "Do you want to set up a **queue** for players waiting to join this group?\n\n"
            "All queue controls will appear here in the voice channel chat."
        ),
        colour=discord.Colour.green()
    )
    view = StartQueueView(channel)
    await channel.send(embed=embed, view=view)

@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    if not isinstance(channel, discord.VoiceChannel):
        return

    channel_id = channel.id

    if channel_id not in queues and channel_id not in queue_messages and channel_id not in queue_hosts:
        return

    guild = channel.guild

    queued_entries = queues.get(channel_id, []).copy()

    ids = broadcast_messages.pop(channel_id, [])
    if guild is not None and ids:
        broadcast_channel = guild.get_channel(BROADCAST_CHANNEL_ID)
        if isinstance(broadcast_channel, discord.TextChannel):
            for mid in ids:
                try:
                    msg = await broadcast_channel.fetch_message(mid)
                    await msg.delete()
                except discord.NotFound:
                    pass
                except Exception as e:
                    logger.warning(f"Failed to delete broadcast message {mid}: {e}")

    if guild is not None and queued_entries:
        for entry in queued_entries:
            user_id = entry.get("user_id")
            member = guild.get_member(user_id)
            if member is None:
                continue
            try:
                dm = await member.create_dm()
                await dm.send(
                    f"⛔ The waitlist for **{channel.name}** has ended and is no longer active. "
                    "You have been removed from that waitlist."
                )
            except discord.Forbidden:
                pass
            except Exception as e:
                logger.warning(f"Failed to DM user {user_id} about ended waitlist: {e}")

    queues.pop(channel_id, None)
    queue_messages.pop(channel_id, None)
    queue_hosts.pop(channel_id, None)
    notified_next.pop(channel_id, None)
    group_info.pop(channel_id, None)
    queue_locks.pop(channel_id, None)
    queue_last_active.pop(channel_id, None)

@bot.event
async def on_member_remove(member: discord.Member):
    user_id = member.id
    
    for channel_id in list(queues.keys()):
        lock = await get_or_create_lock(channel_id)
        async with lock:
            entries = queues.get(channel_id, [])
            original_length = len(entries)
            entries = [e for e in entries if e["user_id"] != user_id]
            if len(entries) < original_length:
                queues[channel_id] = entries
                logger.info(f"Removed user {user_id} from queue {channel_id} (left server)")
        
        if queue_hosts.get(channel_id) == user_id:
            channel = bot.get_channel(channel_id)
            if isinstance(channel, discord.VoiceChannel):
                await reassign_host_if_needed(channel)
        
        channel = bot.get_channel(channel_id)
        if isinstance(channel, discord.VoiceChannel):
            await update_queue_message(channel)

# =========================
# RUN BOT
# =========================

if __name__ == "__main__":
    logger.info("🎮 queue_bot.py has started")
    logger.info("Attempting to log in to Discord...")

    TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    
    if not TOKEN:
        logger.error("❌ DISCORD_BOT_TOKEN environment variable not set!")
        logger.error("Please set it using: export DISCORD_BOT_TOKEN='your_token_here'")
        logger.error("Or create a .env file with: DISCORD_BOT_TOKEN=your_token_here")
        exit(1)

    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        logger.error("❌ Failed to login. Please check your bot token.")
    except Exception as e:
        logger.error(f"❌ An error occurred: {e}")
