"""
Character Registry Module for Discord Bot
Updated with new registration flow: Class → Name & Power → Guild
"""

import json
import os
from typing import Optional
import discord
from discord.ext import commands

# Import class emojis from main bot
try:
    from Queue_bot_improved import CLASS_EMOJIS
except ImportError:
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
# CHARACTER REGISTRY CONFIG
# =========================

# Channel where the character registry embed will be posted/updated
CHARACTER_REGISTRY_CHANNEL_ID = 1344145494649339955  # <-- REPLACE with your channel ID
ROSTER_TABLE_CHANNEL_ID = 1446002991621472327 

# Available in-game guilds (add more as needed)
AVAILABLE_GUILDS = [
    "EBC Wolves",
    "EBC Corsair",
    "Leveling Guild",     
]

CHARACTER_CLASSES = [
    "Tank", "Cleric", "Bard", "Summoner",
    "Mage", "Ranger", "Rogue", "Fighter"
]

# Classes that need healing power
HEALER_CLASSES = ["Cleric", "Bard", "Summoner"]

CHARACTER_DATA_FILE = "character_registry.json"

# =========================
# CHARACTER DATA STORAGE
# =========================

character_registry: dict[int, dict] = {}
registry_message_id: Optional[int] = None
roster_table_message_ids: list[int] = []


def load_character_data():
    global character_registry
    if os.path.exists(CHARACTER_DATA_FILE):
        try:
            with open(CHARACTER_DATA_FILE, 'r') as f:
                data = json.load(f)
                character_registry = {int(k): v for k, v in data.items()}
            print(f"✅ Loaded {len(character_registry)} character profiles")
        except Exception as e:
            print(f"⚠️ Error loading character data: {e}")
    else:
        character_registry = {}


def save_character_data():
    try:
        with open(CHARACTER_DATA_FILE, 'w') as f:
            json.dump(character_registry, f, indent=2)
    except Exception as e:
        print(f"⚠️ Error saving character data: {e}")


# =========================
# STEP 1: CLASS SELECTION
# =========================

class ClassSelectionView(discord.ui.View):
    def __init__(self, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.add_item(ClassSelect())


class ClassSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=char_class,
                description=f"Play as {char_class}",
                value=char_class
            )
            for char_class in CHARACTER_CLASSES
        ]
        
        super().__init__(
            placeholder="Select your character class",
            options=options,
            min_values=1,
            max_values=1
        )
    
    async def callback(self, interaction: discord.Interaction):
        selected_class = self.values[0]
        
        # Show appropriate modal based on class
        if selected_class in HEALER_CLASSES:
            modal = CharacterInfoModalWithHealing(selected_class)
        else:
            modal = CharacterInfoModal(selected_class)
        
        await interaction.response.send_modal(modal)


# =========================
# STEP 2: CHARACTER INFO MODALS
# =========================

class CharacterInfoModal(discord.ui.Modal, title="Character Information"):
    def __init__(self, selected_class: str):
        super().__init__()
        self.selected_class = selected_class
        
        self.char_name = discord.ui.TextInput(
            label="Character Name",
            placeholder="Enter your in-game character name",
            required=True,
            max_length=50,
        )
        
        self.power_level = discord.ui.TextInput(
            label="Phys/Mag Power",
            placeholder="Enter your physical or magical power (e.g., 1250)",
            required=True,
            max_length=10,
        )
        
        self.add_item(self.char_name)
        self.add_item(self.power_level)
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        power_str = str(self.power_level.value).strip()
        if not power_str.isdigit():
            await interaction.followup.send(
                "❌ Power level must be a number.",
                ephemeral=True
            )
            return
        
        temp_data = {
            "name": str(self.char_name.value).strip(),
            "class": self.selected_class,
            "power_level": int(power_str),
            "healing_power": None
        }
        
        # Show guild selection
        view = GuildSelectionView(temp_data)
        await interaction.followup.send(
            f"✅ Character info saved!\n\n"
            f"**Class:** {self.selected_class}\n"
            f"**Name:** {temp_data['name']}\n"
            f"**Phys/Mag Power:** {temp_data['power_level']:,}\n\n"
            f"**Step 3:** Select your in-game guild:",
            view=view,
            ephemeral=True
        )


class CharacterInfoModalWithHealing(discord.ui.Modal, title="Character Information"):
    def __init__(self, selected_class: str):
        super().__init__()
        self.selected_class = selected_class
        
        self.char_name = discord.ui.TextInput(
            label="Character Name",
            placeholder="Enter your in-game character name",
            required=True,
            max_length=50,
        )
        
        self.power_level = discord.ui.TextInput(
            label="Phys/Mag Power",
            placeholder="Enter your physical or magical power (e.g., 1250)",
            required=True,
            max_length=10,
        )
        
        self.healing_power = discord.ui.TextInput(
            label="Healing Power",
            placeholder="Enter your healing power (e.g., 850)",
            required=True,
            max_length=10,
        )
        
        self.add_item(self.char_name)
        self.add_item(self.power_level)
        self.add_item(self.healing_power)
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        power_str = str(self.power_level.value).strip()
        healing_str = str(self.healing_power.value).strip()
        
        if not power_str.isdigit():
            await interaction.followup.send(
                "❌ Phys/Mag Power must be a number.",
                ephemeral=True
            )
            return
        
        if not healing_str.isdigit():
            await interaction.followup.send(
                "❌ Healing Power must be a number.",
                ephemeral=True
            )
            return
        
        temp_data = {
            "name": str(self.char_name.value).strip(),
            "class": self.selected_class,
            "power_level": int(power_str),
            "healing_power": int(healing_str)
        }
        
        # Show guild selection
        view = GuildSelectionView(temp_data)
        await interaction.followup.send(
            f"✅ Character info saved!\n\n"
            f"**Class:** {self.selected_class}\n"
            f"**Name:** {temp_data['name']}\n"
            f"**Phys/Mag Power:** {temp_data['power_level']:,}\n"
            f"**Healing Power:** {temp_data['healing_power']:,}\n\n"
            f"**Step 3:** Select your in-game guild:",
            view=view,
            ephemeral=True
        )


# =========================
# STEP 3: GUILD SELECTION
# =========================

class GuildSelectionView(discord.ui.View):
    def __init__(self, temp_data: dict, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.temp_data = temp_data
        self.add_item(GuildSelect(temp_data))


class GuildSelect(discord.ui.Select):
    def __init__(self, temp_data: dict):
        self.temp_data = temp_data
        
        options = [
            discord.SelectOption(
                label=guild,
                description=f"Member of {guild}",
                value=guild
            )
            for guild in AVAILABLE_GUILDS
        ]
        
        super().__init__(
            placeholder="Select your guild",
            options=options,
            min_values=1,
            max_values=1
        )
    
    async def callback(self, interaction: discord.Interaction):
        from datetime import datetime
        
        self.temp_data["guilds"] = self.values
        self.temp_data["last_updated"] = datetime.utcnow().isoformat()
        
        # Save to registry
        user_id = interaction.user.id
        character_registry[user_id] = self.temp_data
        save_character_data()
        
        # Build confirmation embed
        embed = discord.Embed(
            title="<:ebccircle:1446026315907076126> Character Registered!",
            description="Your character has been successfully registered and added to the roster.",
            colour=discord.Colour.green()
        )
        embed.add_field(name="Character Name", value=self.temp_data["name"], inline=True)
        embed.add_field(name="Class", value=self.temp_data["class"], inline=True)
        embed.add_field(name="Guild", value=", ".join(self.temp_data["guilds"]), inline=True)
        embed.add_field(name="Phys/Mag Power", value=f"{self.temp_data['power_level']:,}", inline=True)
        
        if self.temp_data.get("healing_power"):
            embed.add_field(name="Healing Power", value=f"{self.temp_data['healing_power']:,}", inline=True)
        
        embed.set_footer(text="Your information is now displayed in the roster channel")
        
        await interaction.response.edit_message(
            content=None,
            embed=embed,
            view=None
        )
        
        await update_registry_embed(interaction.client, interaction.guild)


# =========================
# REGISTRY EMBED BUILDER
# =========================

def build_registry_embed(guild: discord.Guild) -> discord.Embed:
    embed = discord.Embed(
        title="<:ebccircle:1446026315907076126> Character Registry",
        description=(
            "Use the button below to register or update your character information.\n\n"
            f"**Total Registered Characters:** {len(character_registry)}\n\n"
            "Your character information will be displayed in the roster channel."
        ),
        colour=discord.Colour.purple()
    )
    embed.set_footer(text="Click the buttons below to manage your registration")
    embed.timestamp = discord.utils.utcnow()
    
    return embed


async def update_registry_embed(bot: commands.Bot, guild: discord.Guild):
    global registry_message_id
    
    channel = guild.get_channel(CHARACTER_REGISTRY_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        print(f"⚠️ Registry channel {CHARACTER_REGISTRY_CHANNEL_ID} not found")
        return
    
    embed = build_registry_embed(guild)
    view = RegistryControlView()
    
    if registry_message_id:
        try:
            message = await channel.fetch_message(registry_message_id)
            await message.edit(embed=embed, view=view)
        except discord.NotFound:
            registry_message_id = None
            message = await channel.send(embed=embed, view=view)
            registry_message_id = message.id
    else:
        message = await channel.send(embed=embed, view=view)
        registry_message_id = message.id
    
    await update_roster_table(bot, guild)


# =========================
# ROSTER TABLE BUILDER
# =========================

def build_roster_table_embeds(guild: discord.Guild) -> list[discord.Embed]:
    if not character_registry:
        embed = discord.Embed(
            title="<:ebccircle:1446026315907076126> Character Roster",
            description="No characters registered yet.",
            colour=discord.Colour.purple()
        )
        embed.set_footer(text="Use /setupregistry to create the registration form")
        return [embed]
    
    class_order = ["Tank", "Cleric", "Bard", "Summoner", "Mage", "Ranger", "Rogue", "Fighter"]
    
    # Sort characters: Guild > Class > Power
    # SPECIAL CASE: Clerics sort by healing power instead of phys/mag power
    def sort_key(item):
        user_id, data = item
        guild_name = data.get("guilds", ["ZZZ"])[0]
        char_class = data.get("class", "Fighter")
        class_index = class_order.index(char_class) if char_class in class_order else 999
        
        # Clerics sort by healing power (highest first)
        # All other classes sort by phys/mag power (highest first)
        if char_class == "Cleric":
            sort_power = data.get("healing_power") or 0
        else:
            sort_power = data.get("power_level", 0)
        
        return (guild_name, class_index, -sort_power)  # Negative for descending order
    
    sorted_chars = sorted(character_registry.items(), key=sort_key)
    
    # Group by guild, then by class
    guild_groups = {}
    for user_id, data in sorted_chars:
        primary_guild = data.get("guilds", ["No Guild"])[0]
        char_class = data.get("class", "Unknown")
        
        if primary_guild not in guild_groups:
            guild_groups[primary_guild] = {}
        
        if char_class not in guild_groups[primary_guild]:
            guild_groups[primary_guild][char_class] = []
        
        guild_groups[primary_guild][char_class].append((user_id, data))
    
    embeds = []
    current_embed = discord.Embed(
        title="<:ebccircle:1446026315907076126> Character Roster",
        description=f"**Total Characters:** {len(character_registry)}",
        colour=discord.Colour.gold()
    )
    current_embed.timestamp = discord.utils.utcnow()
    current_embed.set_footer(text="Last Updated")
    
    fields_count = 0
    
    for guild_name in AVAILABLE_GUILDS:
        if guild_name not in guild_groups:
            continue
        
        total_guild_members = sum(len(members) for members in guild_groups[guild_name].values())
        
        # Build the guild header with lines above and below
        guild_header = (
            "─────────────────────────────────────\n"
            f"**{guild_name}** — {total_guild_members} members\n"
            "─────────────────────────────────────"
        )
        
        guild_content_lines = []
        
        for char_class in class_order:
            if char_class not in guild_groups[guild_name]:
                continue
            
            members = guild_groups[guild_name][char_class]
            class_emoji = CLASS_EMOJIS.get(char_class, "⚔️")
            
            # Class header
            guild_content_lines.append("")
            guild_content_lines.append(f"{class_emoji} **{char_class}** — {len(members)} member{'s' if len(members) != 1 else ''}")
            guild_content_lines.append("")
            
            # Column headers in code block for alignment
            guild_content_lines.append("```")
            guild_content_lines.append(f"{'Character':<13} {'Power':<8} {'Heal':<7}")
            guild_content_lines.append("─" * 28)
            
            # Add each member as a row
            for user_id, data in members:
                char_name = data.get("name", "Unknown")
                power = data.get("power_level", 0)
                healing = data.get("healing_power")
                
                # Truncate name if too long
                char_name_short = char_name[:12] if len(char_name) > 12 else char_name
                
                # Format power with commas
                power_str = f"{power:,}"
                if len(power_str) > 8:
                    power_str = power_str[:8]
                
                # Format healing as N/A if not present
                healing_str = f"{healing:,}" if healing else "N/A"
                if len(healing_str) > 7:
                    healing_str = healing_str[:7]
                
                # Build the row
                row = f"{char_name_short:<13} {power_str:<8} {healing_str:<7}"
                guild_content_lines.append(row)
            
            guild_content_lines.append("```")
            # Removed one empty line here for tighter spacing
        
        field_value = "\n".join(guild_content_lines)
        
        # Check if we need a new embed
        if fields_count >= 25 or len(current_embed) + len(field_value) + len(guild_header) > 5500:
            embeds.append(current_embed)
            current_embed = discord.Embed(
                title="<:ebccircle:1446026315907076126> Character Roster (continued)",
                colour=discord.Colour.gold()
            )
            current_embed.timestamp = discord.utils.utcnow()
            current_embed.set_footer(text="Last Updated")
            fields_count = 0
        
        # Truncate if field value is too long (1024 char limit per field)
        if len(field_value) > 1024:
            field_value = field_value[:1020] + "..."
        
        current_embed.add_field(
            name=guild_header,
            value=field_value if field_value else "No members",
            inline=False
        )
        fields_count += 1
    
    if fields_count > 0 or not embeds:
        embeds.append(current_embed)
    
    return embeds


async def cleanup_old_roster_messages(bot: commands.Bot, guild: discord.Guild):
    roster_channel = guild.get_channel(ROSTER_TABLE_CHANNEL_ID)
    if not isinstance(roster_channel, discord.TextChannel):
        print(f"⚠️ Roster table channel {ROSTER_TABLE_CHANNEL_ID} not found")
        return
    
    deleted_count = 0
    try:
        async for message in roster_channel.history(limit=100):
            if message.author == bot.user and message.embeds:
                for embed in message.embeds:
                    if embed.title and "Character Roster" in embed.title:
                        try:
                            await message.delete()
                            deleted_count += 1
                            print(f"🗑️ Deleted old roster message {message.id}")
                        except discord.NotFound:
                            pass
                        except Exception as e:
                            print(f"⚠️ Failed to delete old roster message {message.id}: {e}")
                        break
        
        if deleted_count > 0:
            print(f"✅ Cleaned up {deleted_count} old roster table message(s)")
    
    except discord.Forbidden:
        print(f"⚠️ Missing permissions to read/delete messages in roster channel")
    except Exception as e:
        print(f"❌ Error during roster cleanup: {e}")

async def cleanup_old_registry_messages(bot: commands.Bot, guild: discord.Guild):
    global registry_message_id

    registry_channel = guild.get_channel(CHARACTER_REGISTRY_CHANNEL_ID)
    if not isinstance(registry_channel, discord.TextChannel):
        print(f"⚠️ Registry channel {CHARACTER_REGISTRY_CHANNEL_ID} not found")
        return

    deleted_count = 0
    try:
        async for message in registry_channel.history(limit=50):
            if message.author == bot.user and message.embeds:
                for embed in message.embeds:
                    if embed.title and "Character Registry" in embed.title:
                        try:
                            await message.delete()
                            deleted_count += 1
                            print(f"🗑️ Deleted old registry message {message.id}")
                        except discord.NotFound:
                            pass
                        except Exception as e:
                            print(f"⚠️ Failed to delete old registry message {message.id}: {e}")
                        break  # Don't double-handle the same message

        if deleted_count > 0:
            print(f"✅ Cleaned up {deleted_count} old registry message(s)")

        # Clear cached ID so we don't point at a deleted message
        registry_message_id = None

    except discord.Forbidden:
        print("⚠️ Missing permissions to read/delete messages in registry channel")
    except Exception as e:
        print(f"❌ Error during registry cleanup: {e}")


async def update_roster_table(bot: commands.Bot, guild: discord.Guild):
    global roster_table_message_ids
    
    roster_channel = guild.get_channel(ROSTER_TABLE_CHANNEL_ID)
    if not isinstance(roster_channel, discord.TextChannel):
        print(f"⚠️ Roster table channel {ROSTER_TABLE_CHANNEL_ID} not found")
        return
    
    await cleanup_old_roster_messages(bot, guild)
    
    roster_table_message_ids = []
    
    table_embeds = build_roster_table_embeds(guild)
    
    # Add admin buttons to the first embed only
    for i, embed in enumerate(table_embeds):
        if i == 0:
            # First embed gets the admin control buttons
            view = RosterAdminView()
            msg = await roster_channel.send(embed=embed, view=view)
        else:
            # Subsequent embeds have no buttons
            msg = await roster_channel.send(embed=embed)
        
        roster_table_message_ids.append(msg.id)
        print(f"📊 Posted roster table message {msg.id}")


# =========================
# ROSTER ADMIN CONTROLS
# =========================

class RosterAdminView(discord.ui.View):
    def __init__(self, timeout: float = None):
        super().__init__(timeout=timeout)
    
    @discord.ui.button(label="Edit Player", style=discord.ButtonStyle.secondary, emoji="✏️")
    async def edit_player_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if user is admin
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Only administrators can edit player data.",
                ephemeral=True
            )
            return
        
        if not character_registry:
            await interaction.response.send_message(
                "📊 No characters registered yet.",
                ephemeral=True
            )
            return
        
        # Show player selection dropdown
        view = EditPlayerSelectView()
        await interaction.response.send_message(
            "**Select a player to edit:**",
            view=view,
            ephemeral=True
        )
    
    @discord.ui.button(label="Remove Player", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def remove_player_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if user is admin
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Only administrators can remove player data.",
                ephemeral=True
            )
            return
        
        if not character_registry:
            await interaction.response.send_message(
                "📊 No characters registered yet.",
                ephemeral=True
            )
            return
        
        # Show player selection dropdown
        view = RemovePlayerSelectView()
        await interaction.response.send_message(
            "**Select a player to remove:**",
            view=view,
            ephemeral=True
        )


class EditPlayerSelectView(discord.ui.View):
    def __init__(self, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.add_item(EditPlayerSelect())


class EditPlayerSelect(discord.ui.Select):
    def __init__(self):
        # Build options from registered characters
        options = []
        
        for user_id, data in sorted(character_registry.items(), key=lambda x: x[1].get("name", ""))[:25]:
            char_name = data.get("name", "Unknown")
            char_class = data.get("class", "Unknown")
            guild = data.get("guilds", ["No Guild"])[0]
            
            options.append(
                discord.SelectOption(
                    label=f"{char_name} ({char_class})",
                    description=f"{guild} - User ID: {user_id}",
                    value=str(user_id)
                )
            )
        
        if not options:
            options.append(
                discord.SelectOption(
                    label="No players found",
                    value="none"
                )
            )
        
        super().__init__(
            placeholder="Select a player to edit",
            options=options,
            min_values=1,
            max_values=1
        )
    
    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.edit_message(
                content="❌ No players to edit.",
                view=None
            )
            return
        
        user_id = int(self.values[0])
        
        if user_id not in character_registry:
            await interaction.response.edit_message(
                content="❌ Player not found in registry.",
                view=None
            )
            return
        
        data = character_registry[user_id]
        
        # Show edit modal with current data pre-filled
        if data.get("class") in HEALER_CLASSES:
            modal = EditCharacterModalWithHealing(user_id, data)
        else:
            modal = EditCharacterModal(user_id, data)
        
        await interaction.response.send_modal(modal)


class EditCharacterModal(discord.ui.Modal, title="Edit Character"):
    def __init__(self, user_id: int, current_data: dict):
        super().__init__()
        self.user_id = user_id
        self.current_data = current_data
        
        self.char_name = discord.ui.TextInput(
            label="Character Name",
            default=current_data.get("name", ""),
            required=True,
            max_length=50,
        )
        
        self.power_level = discord.ui.TextInput(
            label="Phys/Mag Power",
            default=str(current_data.get("power_level", "")),
            required=True,
            max_length=10,
        )
        
        self.add_item(self.char_name)
        self.add_item(self.power_level)
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        power_str = str(self.power_level.value).strip()
        if not power_str.isdigit():
            await interaction.followup.send(
                "❌ Power level must be a number.",
                ephemeral=True
            )
            return
        
        # Update the character data
        character_registry[self.user_id]["name"] = str(self.char_name.value).strip()
        character_registry[self.user_id]["power_level"] = int(power_str)
        
        from datetime import datetime
        character_registry[self.user_id]["last_updated"] = datetime.utcnow().isoformat()
        
        save_character_data()
        
        await interaction.followup.send(
            f"✅ Character **{self.char_name.value}** has been updated successfully!",
            ephemeral=True
        )
        
        # Update registry and roster
        await update_registry_embed(interaction.client, interaction.guild)


class EditCharacterModalWithHealing(discord.ui.Modal, title="Edit Character"):
    def __init__(self, user_id: int, current_data: dict):
        super().__init__()
        self.user_id = user_id
        self.current_data = current_data
        
        self.char_name = discord.ui.TextInput(
            label="Character Name",
            default=current_data.get("name", ""),
            required=True,
            max_length=50,
        )
        
        self.power_level = discord.ui.TextInput(
            label="Phys/Mag Power",
            default=str(current_data.get("power_level", "")),
            required=True,
            max_length=10,
        )
        
        self.healing_power = discord.ui.TextInput(
            label="Healing Power",
            default=str(current_data.get("healing_power", "")),
            required=True,
            max_length=10,
        )
        
        self.add_item(self.char_name)
        self.add_item(self.power_level)
        self.add_item(self.healing_power)
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        power_str = str(self.power_level.value).strip()
        healing_str = str(self.healing_power.value).strip()
        
        if not power_str.isdigit():
            await interaction.followup.send(
                "❌ Phys/Mag Power must be a number.",
                ephemeral=True
            )
            return
        
        if not healing_str.isdigit():
            await interaction.followup.send(
                "❌ Healing Power must be a number.",
                ephemeral=True
            )
            return
        
        # Update the character data
        character_registry[self.user_id]["name"] = str(self.char_name.value).strip()
        character_registry[self.user_id]["power_level"] = int(power_str)
        character_registry[self.user_id]["healing_power"] = int(healing_str)
        
        from datetime import datetime
        character_registry[self.user_id]["last_updated"] = datetime.utcnow().isoformat()
        
        save_character_data()
        
        await interaction.followup.send(
            f"✅ Character **{self.char_name.value}** has been updated successfully!",
            ephemeral=True
        )
        
        # Update registry and roster
        await update_registry_embed(interaction.client, interaction.guild)


class RemovePlayerSelectView(discord.ui.View):
    def __init__(self, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.add_item(RemovePlayerSelect())


class RemovePlayerSelect(discord.ui.Select):
    def __init__(self):
        # Build options from registered characters
        options = []
        
        for user_id, data in sorted(character_registry.items(), key=lambda x: x[1].get("name", ""))[:25]:
            char_name = data.get("name", "Unknown")
            char_class = data.get("class", "Unknown")
            guild = data.get("guilds", ["No Guild"])[0]
            
            options.append(
                discord.SelectOption(
                    label=f"{char_name} ({char_class})",
                    description=f"{guild} - User ID: {user_id}",
                    value=str(user_id)
                )
            )
        
        if not options:
            options.append(
                discord.SelectOption(
                    label="No players found",
                    value="none"
                )
            )
        
        super().__init__(
            placeholder="Select a player to remove",
            options=options,
            min_values=1,
            max_values=1
        )
    
    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.edit_message(
                content="❌ No players to remove.",
                view=None
            )
            return
        
        user_id = int(self.values[0])
        
        if user_id not in character_registry:
            await interaction.response.edit_message(
                content="❌ Player not found in registry.",
                view=None
            )
            return
        
        char_name = character_registry[user_id].get("name", "Unknown")
        
        # Show confirmation dialog
        embed = discord.Embed(
            title="⚠️ Remove Player?",
            description=(
                f"Are you sure you want to remove **{char_name}** from the registry?\n\n"
                f"User ID: {user_id}\n\n"
                f"This action cannot be undone."
            ),
            colour=discord.Colour.orange()
        )
        
        view = ConfirmRemovePlayerView(user_id, char_name)
        await interaction.response.edit_message(
            content=None,
            embed=embed,
            view=view
        )


class ConfirmRemovePlayerView(discord.ui.View):
    def __init__(self, user_id: int, char_name: str, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.char_name = char_name
    
    @discord.ui.button(label="Yes, Remove", style=discord.ButtonStyle.danger)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.user_id in character_registry:
            del character_registry[self.user_id]
            save_character_data()
            
            await interaction.response.edit_message(
                content=f"✅ **{self.char_name}** has been removed from the registry.",
                embed=None,
                view=None
            )
            
            # Update registry and roster
            await update_registry_embed(interaction.client, interaction.guild)
        else:
            await interaction.response.edit_message(
                content="❌ Player not found.",
                embed=None,
                view=None
            )
    
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="❌ Removal cancelled.",
            embed=None,
            view=None
        )


# =========================
# REGISTRY CONTROL VIEW
# =========================

class RegistryControlView(discord.ui.View):
    def __init__(self, timeout: float = None):
        super().__init__(timeout=timeout)
    
    @discord.ui.button(label="Register/Update Character", style=discord.ButtonStyle.primary, emoji="📝")
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Show class selection first
        view = ClassSelectionView()
        await interaction.response.send_message(
            "**Step 1:** Select your character class:",
            view=view,
            ephemeral=True
        )
    
    @discord.ui.button(label="View My Character", style=discord.ButtonStyle.secondary, emoji="👤")
    async def view_character_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        
        if user_id not in character_registry:
            await interaction.response.send_message(
                "❌ You haven't registered a character yet. Click **Register/Update Character** to get started!",
                ephemeral=True
            )
            return
        
        data = character_registry[user_id]
        
        embed = discord.Embed(
            title=f"<:ebccircle:1446026315907076126> {data.get('name', 'Unknown')}",
            colour=discord.Colour.blue()
        )
        embed.add_field(name="Class", value=data.get("class", "Unknown"), inline=True)
        embed.add_field(name="Guild", value=", ".join(data.get("guilds", [])), inline=True)
        embed.add_field(name="Phys/Mag Power", value=f"{data.get('power_level', 0):,}", inline=True)
        
        if data.get("healing_power"):
            embed.add_field(name="Healing Power", value=f"{data.get('healing_power', 0):,}", inline=True)
        
        embed.add_field(name="Discord User", value=interaction.user.mention, inline=True)
        
        if "last_updated" in data:
            embed.set_footer(text=f"Last updated: {data['last_updated'][:10]}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @discord.ui.button(label="Delete My Character", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def delete_character_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        
        if user_id not in character_registry:
            await interaction.response.send_message(
                "❌ You don't have a registered character.",
                ephemeral=True
            )
            return
        
        view = ConfirmDeleteView(user_id)
        await interaction.response.send_message(
            "⚠️ Are you sure you want to delete your character registration? This cannot be undone.",
            view=view,
            ephemeral=True
        )


class ConfirmDeleteView(discord.ui.View):
    def __init__(self, user_id: int, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.user_id = user_id
    
    @discord.ui.button(label="Yes, Delete", style=discord.ButtonStyle.danger)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.user_id in character_registry:
            del character_registry[self.user_id]
            save_character_data()
            
            await interaction.response.edit_message(
                content="✅ Your character has been deleted from the registry.",
                view=None
            )
            
            await update_registry_embed(interaction.client, interaction.guild)
        else:
            await interaction.response.edit_message(
                content="❌ Character not found.",
                view=None
            )
    
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="❌ Deletion cancelled.",
            view=None
        )


class ConfirmDeleteAllView(discord.ui.View):
    def __init__(self, timeout: float = 60):
        super().__init__(timeout=timeout)
    
    @discord.ui.button(label="Yes, Delete Everything", style=discord.ButtonStyle.danger)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Store count before deleting
        count = len(character_registry)
        
        # Clear the entire registry
        character_registry.clear()
        save_character_data()
        
        await interaction.response.edit_message(
            content=f"✅ Entire registry deleted. {count} character(s) removed permanently.",
            view=None
        )
        
        # Update the registry embed and roster table
        await update_registry_embed(interaction.client, interaction.guild)
    
    @discord.ui.button(label="No, Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="❌ Registry deletion cancelled. All data is safe.",
            view=None
        )


# =========================
# INITIALIZATION
# =========================

def setup_character_registry(bot: commands.Bot):
    load_character_data()
    
    @bot.tree.command(name="setupregistry", description="Create the character registry embed (Admin only)")
    @discord.app_commands.default_permissions(administrator=True)
    async def setup_registry(interaction: discord.Interaction):
        global registry_message_id
        
        channel = interaction.guild.get_channel(CHARACTER_REGISTRY_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                f"❌ Channel {CHARACTER_REGISTRY_CHANNEL_ID} not found. Update CHARACTER_REGISTRY_CHANNEL_ID in config.",
                ephemeral=True
            )
            return
        
        embed = build_registry_embed(interaction.guild)
        view = RegistryControlView()
        
        message = await channel.send(embed=embed, view=view)
        registry_message_id = message.id
        
        await interaction.response.send_message(
            f"✅ Character registry created in {channel.mention}!",
            ephemeral=True
        )
    
    @bot.tree.command(name="registrystats", description="View character registry statistics (Admin only)")
    @discord.app_commands.default_permissions(administrator=True)
    async def registry_stats(interaction: discord.Interaction):
        if not character_registry:
            await interaction.response.send_message("📊 No characters registered yet.", ephemeral=True)
            return
        
        total_chars = len(character_registry)
        avg_power = sum(data.get("power_level", 0) for data in character_registry.values()) / total_chars
        
        # Average healing for healers
        healers = [d for d in character_registry.values() if d.get("healing_power")]
        avg_healing = sum(d.get("healing_power", 0) for d in healers) / len(healers) if healers else 0
        
        class_counts = {}
        for data in character_registry.values():
            char_class = data.get("class", "Unknown")
            class_counts[char_class] = class_counts.get(char_class, 0) + 1
        
        guild_counts = {}
        for data in character_registry.values():
            for guild in data.get("guilds", []):
                guild_counts[guild] = guild_counts.get(guild, 0) + 1
        
        embed = discord.Embed(
            title="📊 Registry Statistics",
            colour=discord.Colour.gold()
        )
        embed.add_field(name="Total Characters", value=str(total_chars), inline=True)
        embed.add_field(name="Average Power", value=f"{avg_power:,.0f}", inline=True)
        if avg_healing > 0:
            embed.add_field(name="Average Healing", value=f"{avg_healing:,.0f}", inline=True)
        
        class_text = "\n".join(f"{k}: {v}" for k, v in sorted(class_counts.items(), key=lambda x: x[1], reverse=True))
        embed.add_field(name="Class Distribution", value=class_text or "None", inline=False)
        
        guild_text = "\n".join(f"{k}: {v}" for k, v in sorted(guild_counts.items(), key=lambda x: x[1], reverse=True))
        embed.add_field(name="Guild Distribution", value=guild_text or "None", inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @bot.tree.command(name="exportregistry", description="Export character registry as CSV (Admin only)")
    @discord.app_commands.default_permissions(administrator=True)
    async def export_registry(interaction: discord.Interaction):
        if not character_registry:
            await interaction.response.send_message("❌ No characters to export.", ephemeral=True)
            return
        
        import csv
        from io import StringIO
        
        output = StringIO()
        writer = csv.writer(output)
        
        writer.writerow(["Discord ID", "Discord Name", "Character Name", "Class", "Phys/Mag Power", "Healing Power", "Guild", "Last Updated"])
        
        for user_id, data in character_registry.items():
            member = interaction.guild.get_member(user_id)
            discord_name = str(member) if member else f"Unknown ({user_id})"
            
            writer.writerow([
                user_id,
                discord_name,
                data.get("name", ""),
                data.get("class", ""),
                data.get("power_level", 0),
                data.get("healing_power", "") or "",
                ", ".join(data.get("guilds", [])),
                data.get("last_updated", "")
            ])
        
        output.seek(0)
        file = discord.File(fp=StringIO(output.getvalue()), filename="character_registry.csv")
        
        await interaction.response.send_message("📊 Character Registry Export:", file=file, ephemeral=True)
    
    @bot.tree.command(name="setuprostertable", description="Create/refresh the roster table display (Admin only)")
    @discord.app_commands.default_permissions(administrator=True)
    async def setup_roster_table(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        roster_channel = interaction.guild.get_channel(ROSTER_TABLE_CHANNEL_ID)
        if not isinstance(roster_channel, discord.TextChannel):
            await interaction.followup.send(
                f"❌ Roster table channel {ROSTER_TABLE_CHANNEL_ID} not found. Update ROSTER_TABLE_CHANNEL_ID in character_registry.py",
                ephemeral=True
            )
            return
        
        await update_roster_table(interaction.client, interaction.guild)
        
        await interaction.followup.send(
            f"✅ Roster table created/updated in {roster_channel.mention}! Any old roster tables have been removed.",
            ephemeral=True
        )
    
    @bot.tree.command(name="whoiswho", description="Show character names with Discord profiles")
    async def who_is_who(interaction: discord.Interaction):
        """Shows a list of all registered characters with clickable Discord mentions"""
        if not character_registry:
            await interaction.response.send_message(
                "📊 No characters registered yet.",
                ephemeral=True
            )
            return
        
        # Sort by guild and character name
        sorted_chars = sorted(
            character_registry.items(),
            key=lambda x: (x[1].get("guilds", ["ZZZ"])[0], x[1].get("name", ""))
        )
        
        # Group by guild
        guild_groups = {}
        for user_id, data in sorted_chars:
            primary_guild = data.get("guilds", ["No Guild"])[0]
            if primary_guild not in guild_groups:
                guild_groups[primary_guild] = []
            guild_groups[primary_guild].append((user_id, data))
        
        embed = discord.Embed(
            title="<:ebccircle:1446026315907076126> Character Directory",
            description="Character names linked to Discord profiles",
            colour=discord.Colour.blue()
        )
        
        # Add a field for each guild
        for guild_name in AVAILABLE_GUILDS:
            if guild_name not in guild_groups:
                continue
            
            members = guild_groups[guild_name]
            lines = []
            
            for user_id, data in members[:25]:  # Discord limit of 25 per field
                char_name = data.get("name", "Unknown")
                char_class = data.get("class", "Unknown")
                member = interaction.guild.get_member(user_id)
                
                if member:
                    lines.append(f"**{char_name}** ({char_class}) → {member.mention}")
                else:
                    lines.append(f"**{char_name}** ({char_class}) → User {user_id}")
            
            if lines:
                field_value = "\n".join(lines)
                if len(field_value) > 1024:
                    field_value = field_value[:1020] + "..."
                
                embed.add_field(
                    name=f"{guild_name} ({len(members)} members)",
                    value=field_value,
                    inline=False
                )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @bot.tree.command(name="deleteregistry", description="⚠️ DELETE ENTIRE CHARACTER REGISTRY (Admin only)")
    @discord.app_commands.default_permissions(administrator=True)
    async def delete_registry(interaction: discord.Interaction):
        """Deletes the entire character registry with confirmation"""
        if not character_registry:
            await interaction.response.send_message(
                "📊 The registry is already empty.",
                ephemeral=True
            )
            return
        
        count = len(character_registry)
        
        embed = discord.Embed(
            title="⚠️ Delete Entire Registry?",
            description=(
                f"**Are you sure you want to delete the entire guild registry?**\n\n"
                f"This will permanently remove **{count} character(s)** from the database.\n\n"
                f"⛔ **This action is UNRECOVERABLE.**\n"
                f"All character data will be lost forever."
            ),
            colour=discord.Colour.red()
        )
        
        view = ConfirmDeleteAllView()
        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True
        )
    
    @bot.tree.command(name="analyzeraid", description="Analyze a RaidHelper event JSON link with registry data")
    @discord.app_commands.describe(
        event_link="Paste the RaidHelper JSON or web view link for the event"
    )
    async def analyze_raid(interaction: discord.Interaction, event_link: str):
        """
        Analyze a RaidHelper event by fetching its JSON and cross-referencing with the character registry.

        Usage:
        - Open the RaidHelper web view for an event.
        - Click the JSON link.
        - Copy that URL and paste it into this command.
        """

        await interaction.response.defer(ephemeral=True)

        if not character_registry:
            await interaction.followup.send(
                "❌ Character registry is empty. Players need to register first.",
                ephemeral=True
            )
            return

        import re
        import aiohttp

        # --- 1) Extract event ID from whatever RaidHelper link we got ---
        # Handles:
        # - https://raid-helper.dev/api/v2/events/1444207169611235399
        # - https://raid-helper.dev/events/1444207169611235399
        # - https://raid-helper.dev/e/1444207169611235399
        m = re.search(r"raid-helper\.dev/(?:api/v2/events|events|e)/(\d+)", event_link)
        if not m:
            await interaction.followup.send(
                "❌ I couldn't find a valid RaidHelper event ID in that link.\n"
                "Please use the **JSON** link from the RaidHelper web view.",
                ephemeral=True
            )
            return

        event_id = m.group(1)
        api_url = f"https://raid-helper.dev/api/v2/events/{event_id}"

        # --- 2) Fetch JSON from RaidHelper ---
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url) as resp:
                    if resp.status != 200:
                        await interaction.followup.send(
                            f"❌ Failed to fetch RaidHelper data (HTTP {resp.status}).",
                            ephemeral=True
                        )
                        return
                    data = await resp.json()
        except Exception as e:
            await interaction.followup.send(
                f"❌ Error fetching RaidHelper JSON: `{e}`",
                ephemeral=True
            )
            return

        signups = data.get("signUps", [])
        if not signups:
            await interaction.followup.send(
                "⚠️ This RaidHelper event has no signups.",
                ephemeral=True
            )
            return

        # --- 3) Bucket signups by type (Main / Bench / Tentative / Absence) ---
        main_signups = []
        bench_signups = []
        tentative_signups = []
        absence_signups = []
        late_signups = []

        for s in signups:
            class_name = s.get("className", "")
            # Normalise for safety
            c_lower = str(class_name).lower()

            if c_lower == "bench":
                bench_signups.append(s)
            elif c_lower == "tentative":
                tentative_signups.append(s)
            elif c_lower == "absence":
                absence_signups.append(s)
            elif c_lower == "late":
                late_signups.append(s)
            else:
                main_signups.append(s)

        # --- 4) Cross-reference userIds from signups with character_registry ---
        def map_signups(signup_list):
            registered = []
            unregistered = []
            for s in signup_list:
                user_id_str = s.get("userId")
                if not user_id_str:
                    continue
                try:
                    uid = int(user_id_str)
                except ValueError:
                    continue

                reg_data = character_registry.get(uid)
                if reg_data:
                    registered.append((uid, reg_data, s))
                else:
                    unregistered.append(uid)
            return registered, unregistered

        main_registered, main_unregistered = map_signups(main_signups)
        bench_registered, bench_unregistered = map_signups(bench_signups)
        tentative_registered, tentative_unregistered = map_signups(tentative_signups)
        absence_registered, absence_unregistered = map_signups(absence_signups)
        late_registered, late_unregistered = map_signups(late_signups)

        all_unregistered_ids = set(main_unregistered + bench_unregistered + tentative_unregistered + absence_unregistered + late_unregistered)

        if not main_registered and not bench_registered and not tentative_registered and not absence_registered and not late_registered:
            await interaction.followup.send(
                f"📊 Found {len(signups)} signup(s), but **none** have registered characters.\n"
                "Ask them to use the registry button first.",
                ephemeral=True
            )
            return

        # --- 5) Sort and group main signups by class (from registry) ---
        class_order = ["Tank", "Cleric", "Bard", "Summoner", "Mage", "Ranger", "Rogue", "Fighter"]

        def sort_key(item):
            uid, reg, signup = item
            cls = reg.get("class", "Fighter")
            class_index = class_order.index(cls) if cls in class_order else 99
            if cls == "Cleric":
                power = reg.get("healing_power") or 0
            else:
                power = reg.get("power_level") or 0
            return (class_index, -power)

        main_registered.sort(key=sort_key)

        class_groups = {}
        for uid, reg, signup in main_registered:
            cls = reg.get("class", "Unknown")
            class_groups.setdefault(cls, []).append((uid, reg, signup))

        # --- 6) Build output embed ---
        total_registered = (
            len(main_registered)
            + len(bench_registered)
            + len(tentative_registered)
            + len(absence_registered)
            + len(late_registered)
        )

        embed = discord.Embed(
            title="<:ebccircle:1446026315907076126> Raid Signup Analysis",
            colour=discord.Colour.green()
        )

        lines = []
        lines.append(f"**Event ID:** `{event_id}`")
        lines.append(f"**Registered Players (any status):** {total_registered}/{len(signups)}")

        # Main section by class
        lines.append("\n__**MAIN SIGNUPS (by registry class)**__")

        if main_registered:
            for cls in class_order:
                if cls not in class_groups:
                    continue
                members = class_groups[cls]
                emoji = CLASS_EMOJIS.get(cls, "⚔️")
                lines.append(f"\n{emoji} **{cls}** — {len(members)}")
                lines.append("```")
                lines.append(f"{'Character':<13} {'Power':<8} {'Heal':<7} {'RH Role':<7}")
                lines.append("─" * 40)
                for uid, reg, signup in members:
                    name = reg.get("name", "Unknown")[:12]
                    cls_name = reg.get("class", "Unknown")
                    if cls_name == "Cleric":
                        power = reg.get("power_level") or 0
                        heal = reg.get("healing_power") or 0
                    else:
                        power = reg.get("power_level") or 0
                        heal = reg.get("healing_power")
                    rh_role = signup.get("roleName") or ""
                    p_str = f"{power:,}"[:8]
                    h_str = f"{heal:,}"[:7] if heal else "N/A"
                    role_str = rh_role[:7]
                    lines.append(f"{name:<13} {p_str:<8} {h_str:<7} {role_str:<7}")
                lines.append("```")
        else:
            lines.append("\n*(No main signups with registered characters)*")

        # Helper to print a simple list section
        def add_section(title: str, reg_list, unreg_list):
            if not reg_list and not unreg_list:
                return
            lines.append(f"\n__**{title}**__")
            if reg_list:
                lines.append("```")
                lines.append(f"{'Character':<13} {'Class':<10} {'RH Role':<7}")
                lines.append("─" * 32)
                for uid, reg, signup in reg_list:
                    name = reg.get("name", "Unknown")[:12]
                    cls = reg.get("class", "Unknown")[:10]
                    rh_role = signup.get("roleName") or ""
                    role_str = rh_role[:7]
                    lines.append(f"{name:<13} {cls:<10} {role_str:<7}")
                lines.append("```")
            if unreg_list:
                # Show up to 10 unregistered mentions
                mentions = []
                for uid in unreg_list[:10]:
                    member = interaction.guild.get_member(uid)
                    if member:
                        mentions.append(member.mention)
                if mentions:
                    lines.append(f"Unregistered: {', '.join(mentions)}")
                else:
                    lines.append("Unregistered players present.")

        add_section("BENCH", bench_registered, bench_unregistered)
        add_section("TENTATIVE", tentative_registered, tentative_unregistered)
        add_section("ABSENCE", absence_registered, absence_unregistered)
        add_section("LATE", late_registered, late_unregistered)

        # Global unregistered summary
        if all_unregistered_ids:
            lines.append(f"\n⚠️ **Total unregistered Discord users:** {len(all_unregistered_ids)}")
            # Show a few of them
            shown = []
            for uid in list(all_unregistered_ids)[:10]:
                member = interaction.guild.get_member(uid)
                if member:
                    shown.append(member.mention)
            if shown:
                lines.append(", ".join(shown))

        description = "\n".join(lines)
        if len(description) > 4000:
            embed.description = (
                f"**Event ID:** `{event_id}`\n"
                f"**Registered Players:** {total_registered}/{len(signups)}\n\n"
                "Full breakdown is too large to display; try filtering the event or limiting the signup size."
            )
        else:
            embed.description = description

        await interaction.followup.send(embed=embed, ephemeral=True)
    
    async def on_ready_registry_cleanup():
        await bot.wait_until_ready()
        
        print(f"🔍 Character Registry startup check...")
        print(f"📊 Found {len(character_registry)} registered character(s)")
        
        for guild in bot.guilds:
            # ---------------------------
            # 1) Clean & recreate REGISTRY EMBED
            # ---------------------------
            registry_channel = guild.get_channel(CHARACTER_REGISTRY_CHANNEL_ID)
            if isinstance(registry_channel, discord.TextChannel):
                print(f"🧹 Running registry embed cleanup for {guild.name}...")
                await cleanup_old_registry_messages(bot, guild)

                try:
                    embed = build_registry_embed(guild)
                    view = RegistryControlView()
                    global registry_message_id
                    message = await registry_channel.send(embed=embed, view=view)
                    registry_message_id = message.id
                    print(f"✅ Reposted registry embed {message.id} in {registry_channel.name}")
                except Exception as e:
                    print(f"❌ Failed to recreate registry embed: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                print(f"⚠️ Registry channel {CHARACTER_REGISTRY_CHANNEL_ID} not found")

            # ---------------------------
            # 2) Clean & recreate ROSTER TABLE (using the same helper as /setuprostertable)
            # ---------------------------
            roster_channel = guild.get_channel(ROSTER_TABLE_CHANNEL_ID)
            if isinstance(roster_channel, discord.TextChannel):
                print(f"🧹 Running roster table cleanup for {guild.name}...")
                
                if character_registry:
                    print(f"📊 Recreating roster table with {len(character_registry)} character(s)...")
                    try:
                        await update_roster_table(bot, guild)
                        print(f"✅ Roster table recreated successfully")
                    except Exception as e:
                        print(f"❌ Failed to recreate roster table: {e}")
                        import traceback
                        traceback.print_exc()
                else:
                    # Still clean up any old tables if we wiped the registry
                    await cleanup_old_roster_messages(bot, guild)
                    print(f"ℹ️ No characters registered, skipping roster recreation")
            else:
                print(f"⚠️ Roster channel {ROSTER_TABLE_CHANNEL_ID} not found")

    
    bot.loop.create_task(on_ready_registry_cleanup())

    
    print("✅ Character Registry module loaded")
    print(f"📋 Slash commands added: /setupregistry, /registrystats, /exportregistry, /setuprostertable, /whoiswho, /deleteregistry")

