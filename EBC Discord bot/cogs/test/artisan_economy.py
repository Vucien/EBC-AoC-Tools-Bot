"""
Artisan Economy Cog for EBC Discord Bot
Standalone cog that works alongside queue_bot_improved.py
"""

import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# =========================
# CONFIGURATION
# =========================

# Import these from your queue_bot_improved.py or define here
ARTISAN_WORKORDERS_CHANNEL_ID = 1448237323182538885
ARTISAN_PURCHASES_CHANNEL_ID = 1448237408037372035
ARTISAN_TREASURY_CHANNEL_ID = 1448268131146661918
ARTISAN_LOGS_CHANNEL_ID = 1448276540390375475
ARTISAN_ROSTER_CHANNEL_ID = 1448276835153481868
ARTISAN_OPTIN_ROLE_ID = 1366045502818484284
ARTISAN_MANAGER_ROLE_IDS = [1448277106223222804]

# Data files
ARTISAN_DATA_FILE = "artisan_data.json"

# =========================
# ARTISAN ECONOMY COG
# =========================

class ArtisanEconomy(commands.Cog):
    """Manages artisan economy, work orders, and guild treasury"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
        # Data structures
        self.work_orders = {}  # {order_id: order_data}
        self.donations = {}  # {user_id: donation_data}
        self.treasury_balance = 0
        self.treasury_transactions = []
        
        # Message IDs for updating embeds
        self.control_panel_message_id = None
        self.treasury_message_id = None
        self.work_order_message_ids = []  # List of work order embed message IDs
        
        # Load existing data
        self.load_data()
        
        logger.info("✅ Artisan Economy cog loaded")
    
    async def cog_load(self):
        """Called when the cog is loaded - run cleanup"""
        logger.info("🔧 Artisan Economy: Running startup cleanup...")
        await self.bot.wait_until_ready()
        await self.cleanup_old_embeds()
        logger.info("✅ Artisan Economy: Startup cleanup complete")
    
    async def cleanup_old_embeds(self):
        """
        Refresh control panel, treasury and active work order embeds on startup.

        - Edits existing messages in-place where possible (so they don't move).
        - Recreates any missing messages as a fallback.
        """
        workorders_channel = self.bot.get_channel(ARTISAN_WORKORDERS_CHANNEL_ID)
        treasury_channel = self.bot.get_channel(ARTISAN_TREASURY_CHANNEL_ID)

        if not isinstance(workorders_channel, discord.TextChannel):
            logger.error(f"❌ Work orders channel not found: {ARTISAN_WORKORDERS_CHANNEL_ID}")

        if not isinstance(treasury_channel, discord.TextChannel):
            logger.error(f"❌ Treasury channel not found: {ARTISAN_TREASURY_CHANNEL_ID}")

        # -------------------------
        # CONTROL PANEL (in place)
        # -------------------------
        if isinstance(workorders_channel, discord.TextChannel):
            if self.control_panel_message_id:
                try:
                    # This will fetch and edit the existing message in place
                    await self.update_control_panel()
                    logger.info("✅ Refreshed existing control panel embed in-place")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to refresh control panel, posting new one: {e}")
                    await self.post_control_panel(workorders_channel)
                    logger.info("📌 Posted new control panel embed (old one missing or invalid)")
            else:
                # No stored ID – create a fresh control panel
                await self.post_control_panel(workorders_channel)
                logger.info("📌 Posted control panel embed (no previous ID found)")

        # -------------------------
        # TREASURY (in place)
        # -------------------------
        if isinstance(treasury_channel, discord.TextChannel):
            if self.treasury_message_id:
                try:
                    await self.update_treasury_embed()
                    logger.info("✅ Refreshed existing treasury embed in-place")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to refresh treasury embed, posting new one: {e}")
                    await self.post_treasury_embed(treasury_channel)
                    logger.info("📌 Posted new treasury embed (old one missing or invalid)")
            else:
                await self.post_treasury_embed(treasury_channel)
                logger.info("📌 Posted treasury embed (no previous ID found)")

        # -------------------------
        # ACTIVE WORK ORDERS
        # -------------------------
        if isinstance(workorders_channel, discord.TextChannel):
            for order_id, order in self.work_orders.items():
                # Only bother with active orders that have a message_id
                if order.get("status") == "active" and order.get("message_id"):
                    try:
                        await self.update_work_order_embed(order_id)
                        logger.info(f"🔁 Refreshed work order embed: {order_id}")
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to refresh work order {order_id}: {e}")

    
    async def post_control_panel(self, channel: discord.TextChannel):
        """Post the control panel embed"""
        # Count active work orders
        active_orders = len([wo for wo in self.work_orders.values() if wo.get('status') == 'active'])
        
        embed = discord.Embed(
            title="🔨 Artisan Economy Control Panel",
            description=(
                "**Welcome to the EBC Artisan Economy!**\n\n"
                "This system tracks:\n"
                "• Work orders for crafting projects\n"
                "• Material donations and contribution points\n"
                "• Guild treasury for purchases and sales\n\n"
                "Use the buttons below to interact with the system."
            ),
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="📋 Active Work Orders",
            value=str(active_orders),
            inline=True
        )
        
        embed.set_footer(text="Track your contributions and earn points!")
        
        view = ArtisanControlView(self)
        msg = await channel.send(embed=embed, view=view)
        self.control_panel_message_id = msg.id
        self.save_data()
        logger.info(f"✅ Posted control panel embed (ID: {msg.id})")
    
    async def post_treasury_embed(self, channel: discord.TextChannel):
        """Post the treasury embed"""
        embed = discord.Embed(
            title="💰 Guild Treasury",
            description=f"**Current Balance:** {self.treasury_balance:,} gold",
            color=discord.Color.gold()
        )
        
        # Show recent transactions (last 10)
        recent = self.treasury_transactions[-10:] if self.treasury_transactions else []
        
        if recent:
            transaction_text = []
            for txn in reversed(recent):
                amount = txn.get('amount', 0)
                desc = txn.get('description', 'Unknown')
                date = txn.get('date', '')[:10]
                user_id = txn.get('user_id')
                
                sign = "+" if amount > 0 else ""
                user_mention = f"<@{user_id}>" if user_id else "System"
                transaction_text.append(f"`{date}` {sign}{amount:,}g - {desc} ({user_mention})")
            
            embed.add_field(
                name="📜 Recent Transactions",
                value="\n".join(transaction_text),
                inline=False
            )
        else:
            embed.add_field(
                name="📜 Recent Transactions",
                value="*No transactions yet*",
                inline=False
            )
        
        embed.set_footer(text="Last updated")
        embed.timestamp = datetime.utcnow()
        
        view = TreasuryManagementView(self)
        msg = await channel.send(embed=embed, view=view)
        self.treasury_message_id = msg.id
        self.save_data()
        logger.info(f"✅ Posted treasury embed (ID: {msg.id})")
    
    def generate_order_id(self) -> str:
        """Generate a unique order ID"""
        import uuid
        return str(uuid.uuid4())[:8]
    
    def calculate_donation_points(self, quantity: int, item_type: str = "material") -> int:
        """Calculate points awarded for donations"""
        # Base points per item
        base_points = {
            "material": 1,
            "rare_material": 3,
            "gold": 1  # 1 point per gold
        }
        return quantity * base_points.get(item_type, 1)
    
    async def send_donation_confirmation(
        self,
        interaction: discord.Interaction,
        donor_id: int,
        recipient_id: int,
        order_id: str,
        material_name: str,
        quantity: int | None = None,
    ):
        """
        Used by the DonationQuantityModal to send a donation confirmation DM
        to the selected Artisan Manager (recipient).
        """

        # --- Look up work order and material ---
        order = self.work_orders.get(order_id)
        if not order:
            logger.warning(f"[Artisan] send_donation_confirmation: work order '{order_id}' not found")
            return

        materials = order.get("materials", {})
        mat_data = materials.get(material_name)
        if not mat_data:
            logger.warning(
                f"[Artisan] send_donation_confirmation: material '{material_name}' not in order '{order_id}'"
            )
            return

        rarity = mat_data.get("rarity", "Common")
        needed = mat_data.get("needed", 0)
        donated = mat_data.get("donated", 0)
        remaining = max(0, needed - donated)

        # If quantity wasn’t provided, default to remaining (or 1 if none left)
        if quantity is None or quantity <= 0:
            quantity = remaining if remaining > 0 else 1

        dp_per_item = mat_data.get("dp_per_item", 0)
        total_dp = dp_per_item * quantity

        # --- Resolve donor & manager users ---
        guild = interaction.guild
        donor = guild.get_member(donor_id) if guild else None
        manager = guild.get_member(recipient_id) if guild else None

        if donor is None:
            donor = self.bot.get_user(donor_id)
        if manager is None:
            manager = self.bot.get_user(recipient_id)

        if donor is None:
            logger.warning(f"[Artisan] send_donation_confirmation: donor user '{donor_id}' not found")
            return
        if manager is None:
            logger.warning(f"[Artisan] send_donation_confirmation: manager user '{recipient_id}' not found")
            return

        donor_name = donor.mention if isinstance(donor, discord.Member) else str(donor)
        manager_name = manager.mention if isinstance(manager, discord.Member) else str(manager)

        # --- Build confirmation embed shown in the MANAGER's DM ---
        confirm_embed = discord.Embed(
            title="Confirm Work Order Donation",
            description=(
                "A donation has been submitted for this work order.\n\n"
                "If everything looks correct, press **Confirm**.\n"
                "If something is wrong, press **Decline** or **Edit**."
            ),
            colour=discord.Colour.gold(),
        )

        confirm_embed.add_field(name="Work Order ID", value=order_id, inline=False)
        confirm_embed.add_field(name="Material", value=material_name, inline=True)
        confirm_embed.add_field(name="Rarity", value=rarity, inline=True)
        confirm_embed.add_field(name="Quantity", value=str(quantity), inline=True)
        confirm_embed.add_field(name="DP Per Item", value=str(dp_per_item), inline=True)
        confirm_embed.add_field(name="Total DP", value=str(total_dp), inline=True)
        confirm_embed.add_field(name="Donor (Recorded For)", value=donor_name, inline=False)
        confirm_embed.add_field(name="Recorded By (You)", value=manager_name, inline=False)
        confirm_embed.set_footer(text="This donation will not be recorded until it is confirmed.")

        # --- View that handles Confirm / Decline / Edit in the DM ---
        confirm_view = DonationConfirmationView(
            cog=self,
            order_id=order_id,
            material_name=material_name,
            quantity=quantity,
            donor_id=donor_id,
            recorder_id=recipient_id,
        )

        # --- DM the manager with the confirmation embed ---
        try:
            dm = await manager.create_dm()
            await dm.send(embed=confirm_embed, view=confirm_view)
        except discord.Forbidden:
            logger.warning(
                f"[Artisan] Could not DM manager '{recipient_id}' for donation confirmation "
                "(DMs disabled or blocked)."
            )
        except Exception as e:
            logger.error(f"[Artisan] Failed to send donation confirmation DM: {e}")

    
    async def update_control_panel(self):
        """Update the control panel embed"""
        if not self.control_panel_message_id:
            return
        
        channel = self.bot.get_channel(ARTISAN_WORKORDERS_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            return
        
        try:
            message = await channel.fetch_message(self.control_panel_message_id)
        except:
            return
        
        # Count active work orders
        active_orders = len([wo for wo in self.work_orders.values() if wo.get('status') == 'active'])
        
        embed = discord.Embed(
            title="🔨 Artisan Economy Control Panel",
            description=(
                "**Welcome to the EBC Artisan Economy!**\n\n"
                "This system tracks:\n"
                "• Work orders for crafting projects\n"
                "• Material donations and contribution points\n"
                "• Guild treasury for purchases and sales\n\n"
                "Use the buttons below to interact with the system."
            ),
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="📋 Active Work Orders",
            value=str(active_orders),
            inline=True
        )
        
        embed.set_footer(text="Track your contributions and earn points!")
        
        view = ArtisanControlView(self)
        
        try:
            await message.edit(embed=embed, view=view)
        except Exception as e:
            logger.error(f"Failed to update control panel: {e}")
    
    def load_data(self):
        """Load artisan data from JSON"""
        if os.path.exists(ARTISAN_DATA_FILE):
            try:
                with open(ARTISAN_DATA_FILE, 'r') as f:
                    data = json.load(f)
                    self.work_orders = data.get('work_orders', {})
                    self.donations = data.get('donations', {})
                    self.treasury_balance = data.get('treasury_balance', 0)
                    self.treasury_transactions = data.get('treasury_transactions', [])
                    self.control_panel_message_id = data.get('control_panel_message_id')
                    self.treasury_message_id = data.get('treasury_message_id')
                    self.work_order_message_ids = data.get('work_order_message_ids', [])
                logger.info(f"Loaded artisan data: {len(self.work_orders)} work orders")
            except Exception as e:
                logger.error(f"Error loading artisan data: {e}")
        else:
            logger.info("No existing artisan data found, starting fresh")
    
    def save_data(self):
        """Save artisan data to JSON"""
        try:
            data = {
                'work_orders': self.work_orders,
                'donations': self.donations,
                'treasury_balance': self.treasury_balance,
                'treasury_transactions': self.treasury_transactions,
                'control_panel_message_id': self.control_panel_message_id,
                'treasury_message_id': self.treasury_message_id,
                'work_order_message_ids': self.work_order_message_ids
            }
            with open(ARTISAN_DATA_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving artisan data: {e}")
    
    async def update_treasury_embed(self):
        """Update the treasury embed display"""
        if not self.treasury_message_id:
            return
        
        channel = self.bot.get_channel(ARTISAN_TREASURY_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            return
        
        try:
            message = await channel.fetch_message(self.treasury_message_id)
        except:
            return
        
        # Build treasury embed
        embed = discord.Embed(
            title="💰 Guild Treasury",
            description=f"**Current Balance:** {self.treasury_balance:,} gold",
            color=discord.Color.gold()
        )
        
        # Show recent transactions (last 10)
        recent = self.treasury_transactions[-10:] if self.treasury_transactions else []
        
        if recent:
            transaction_text = []
            for txn in reversed(recent):
                amount = txn.get('amount', 0)
                desc = txn.get('description', 'Unknown')
                date = txn.get('date', '')[:10]
                user_id = txn.get('user_id')
                
                sign = "+" if amount > 0 else ""
                user_mention = f"<@{user_id}>" if user_id else "System"
                transaction_text.append(f"`{date}` {sign}{amount:,}g - {desc} ({user_mention})")
            
            embed.add_field(
                name="📜 Recent Transactions",
                value="\n".join(transaction_text),
                inline=False
            )
        else:
            embed.add_field(
                name="📜 Recent Transactions",
                value="*No transactions yet*",
                inline=False
            )
        
        embed.set_footer(text="Last updated")
        embed.timestamp = datetime.utcnow()
        
        view = TreasuryManagementView(self)
        
        try:
            await message.edit(embed=embed, view=view)
        except Exception as e:
            logger.error(f"Failed to update treasury embed: {e}")
    
    async def post_work_order_embed(self, order_id: str):
        """Post a new work order embed"""
        channel = self.bot.get_channel(ARTISAN_WORKORDERS_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            return
        
        order = self.work_orders.get(order_id)
        if not order:
            return
        
        embed = self.build_work_order_embed(order)
        view = WorkOrderView(self, order_id)
        
        try:
            msg = await channel.send(embed=embed, view=view)
            order['message_id'] = msg.id
            self.work_order_message_ids.append(msg.id)
            self.save_data()
        except Exception as e:
            logger.error(f"Failed to post work order embed: {e}")
    
    async def update_work_order_embed(self, order_id: str):
        """Update an existing work order embed, or recreate it if the message is gone"""
        order = self.work_orders.get(order_id)
        if not order or 'message_id' not in order:
            return

        channel = self.bot.get_channel(ARTISAN_WORKORDERS_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            return

        try:
            # Try to fetch the existing message
            message = await channel.fetch_message(order['message_id'])
        except discord.NotFound:
            # Message was deleted – recreate the work order message
            logger.warning(f"ℹ️ Work order message not found for {order_id}, re-posting embed")
            await self.post_work_order_embed(order_id)
            return
        except Exception as e:
            logger.error(f"Failed to fetch work order message for {order_id}: {e}")
            return

        # If we got the message, edit it in place
        try:
            embed = self.build_work_order_embed(order)
            view = WorkOrderView(self, order_id)
            await message.edit(embed=embed, view=view)
        except Exception as e:
            logger.error(f"Failed to update work order embed for {order_id}: {e}")
    
    def build_work_order_embed(self, order: dict) -> discord.Embed:
        """Build embed for a work order"""
        status = order.get('status', 'active')
        created_by = order.get('created_by')
        order_id = order.get('order_id', 'Unknown')
        
        # Set color based on status
        if status == 'completed':
            color = discord.Color.green()
            title_prefix = "✅"
        elif status == 'cancelled':
            color = discord.Color.red()
            title_prefix = "❌"
        else:
            color = discord.Color.blue()
            title_prefix = "📋"
        
        embed = discord.Embed(
            title=f"{title_prefix} Work Order",
            description=f"**Order ID:** `{order_id}`",
            color=color
        )
        
        # Created by
        if created_by:
            embed.add_field(
                name="Created By",
                value=f"<@{created_by}>",
                inline=True
            )
        
        # Materials needed
        materials = order.get('materials', {})
        if materials:
            material_lines = []
            for mat_name, mat_data in materials.items():
                needed = mat_data.get('needed', 0)
                donated = mat_data.get('donated', 0)
                remaining = max(0, needed - donated)
                rarity = mat_data.get('rarity', 'Common')
                dp_per_item = mat_data.get('dp_per_item', 0)
                
                if donated >= needed:
                    status_icon = "✅"
                elif donated > 0:
                    status_icon = "🔄"
                else:
                    status_icon = "⬜"
                
                material_lines.append(
                    f"{status_icon} **{mat_name}** ({rarity})\n"
                    f"   {donated}/{needed} ({remaining} remaining) - {dp_per_item} DP/item"
                )
            
            embed.add_field(
                name="📦 Materials",
                value="\n".join(material_lines),
                inline=False
            )
        
        # Contributors
        contributors = order.get('contributors', {})
        if contributors:
            contrib_list = []
            for user_id, points in sorted(contributors.items(), key=lambda x: -x[1])[:5]:
                contrib_list.append(f"<@{user_id}>: {points} DP")
            
            embed.add_field(
                name="👥 Top Contributors",
                value="\n".join(contrib_list),
                inline=False
            )
        
        # Status footer
        if status == 'active':
            embed.set_footer(text="Click 'Donate Materials' to contribute")
        elif status == 'completed':
            completed_date = order.get('completed_at', '')[:10]
            embed.set_footer(text=f"Completed on {completed_date}")
        
        return embed
    
    async def delete_work_order_embed(self, order_id: str):
        """Delete a work order embed from the channel"""
        order = self.work_orders.get(order_id)
        if not order or 'message_id' not in order:
            return
        
        channel = self.bot.get_channel(ARTISAN_WORKORDERS_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            return
        
        try:
            message = await channel.fetch_message(order['message_id'])
            await message.delete()
            logger.info(f"🗑️ Deleted work order embed for {order_id}")
        except discord.NotFound:
            logger.warning(f"⚠️ Work order embed for {order_id} already deleted")
        except Exception as e:
            logger.error(f"❌ Failed to delete work order embed for {order_id}: {e}")
    
    async def log_work_order_cancellation(self, order_id: str, cancelled_by_id: int):
        """Log detailed work order cancellation to admin channel"""
        order = self.work_orders.get(order_id)
        if not order:
            return
        
        log_channel = self.bot.get_channel(ARTISAN_LOGS_CHANNEL_ID)
        if not isinstance(log_channel, discord.TextChannel):
            return
        
        # Build detailed log embed
        log_embed = discord.Embed(
            title="❌ Work Order Cancelled",
            description=f"**Order ID:** `{order_id}`",
            color=discord.Color.red()
        )
        
        log_embed.add_field(
            name="Cancelled By",
            value=f"<@{cancelled_by_id}>",
            inline=True
        )
        
        log_embed.add_field(
            name="Created By",
            value=f"<@{order.get('created_by', 'Unknown')}>",
            inline=True
        )
        
        # Materials breakdown with progress
        materials = order.get('materials', {})
        if materials:
            mat_lines = []
            total_needed = 0
            total_donated = 0
            
            for mat_name, mat_data in materials.items():
                needed = mat_data.get('needed', 0)
                donated = mat_data.get('donated', 0)
                rarity = mat_data.get('rarity', 'Common')
                dp_per_item = mat_data.get('dp_per_item', 0)
                
                total_needed += needed
                total_donated += donated
                
                percent = int((donated / needed) * 100) if needed > 0 else 0
                
                mat_lines.append(
                    f"**{mat_name}** ({rarity})\n"
                    f"  ├ Progress: {donated}/{needed} ({percent}%)\n"
                    f"  └ Value: {dp_per_item} DP/item"
                )
            
            # Overall progress
            overall_percent = int((total_donated / total_needed) * 100) if total_needed > 0 else 0
            
            log_embed.add_field(
                name=f"📦 Materials ({len(materials)} types)",
                value="\n\n".join(mat_lines),
                inline=False
            )
            
            log_embed.add_field(
                name="Overall Progress",
                value=f"{overall_percent}% complete ({total_donated}/{total_needed} items)",
                inline=False
            )
        
        # Contributors
        contributors = order.get('contributors', {})
        if contributors:
            contrib_lines = []
            total_dp_contributed = sum(contributors.values())
            
            for user_id, points in sorted(contributors.items(), key=lambda x: -x[1])[:10]:
                contrib_lines.append(f"<@{user_id}>: **{points}** DP")
            
            if len(contributors) > 10:
                contrib_lines.append(f"*...and {len(contributors) - 10} more*")
            
            log_embed.add_field(
                name=f"👥 Contributors ({len(contributors)} members, {total_dp_contributed} total DP)",
                value="\n".join(contrib_lines),
                inline=False
            )
        else:
            log_embed.add_field(
                name="👥 Contributors",
                value="*No donations recorded*",
                inline=False
            )
        
        # Timestamps
        created_at = order.get('created_at', '')
        if created_at:
            try:
                created_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                log_embed.add_field(
                    name="Created",
                    value=created_date.strftime('%Y-%m-%d %H:%M UTC'),
                    inline=True
                )
            except:
                pass
        
        log_embed.timestamp = datetime.utcnow()
        
        try:
            await log_channel.send(embed=log_embed)
        except Exception as e:
            logger.error(f"Failed to log work order cancellation: {e}")
    
    async def log_work_order_completion(self, order_id: str, completed_by_id: int):
        """Log detailed work order completion to admin channel"""
        order = self.work_orders.get(order_id)
        if not order:
            return
        
        log_channel = self.bot.get_channel(ARTISAN_LOGS_CHANNEL_ID)
        if not isinstance(log_channel, discord.TextChannel):
            return
        
        # Build detailed log embed
        log_embed = discord.Embed(
            title="✅ Work Order Completed",
            description=f"**Order ID:** `{order_id}`",
            color=discord.Color.green()
        )
        
        log_embed.add_field(
            name="Completed By",
            value=f"<@{completed_by_id}>",
            inline=True
        )
        
        log_embed.add_field(
            name="Created By",
            value=f"<@{order.get('created_by', 'Unknown')}>",
            inline=True
        )
        
        # Materials breakdown
        materials = order.get('materials', {})
        if materials:
            mat_lines = []
            total_needed = 0
            total_donated = 0
            
            for mat_name, mat_data in materials.items():
                needed = mat_data.get('needed', 0)
                donated = mat_data.get('donated', 0)
                rarity = mat_data.get('rarity', 'Common')
                dp_per_item = mat_data.get('dp_per_item', 0)
                
                total_needed += needed
                total_donated += donated
                
                mat_lines.append(
                    f"**{mat_name}** ({rarity})\n"
                    f"  ├ Fulfilled: {donated}/{needed}\n"
                    f"  └ Value: {dp_per_item} DP/item"
                )
            
            log_embed.add_field(
                name=f"📦 Materials ({len(materials)} types)",
                value="\n\n".join(mat_lines),
                inline=False
            )
            
            log_embed.add_field(
                name="Total Items",
                value=f"{total_donated}/{total_needed} fulfilled",
                inline=False
            )
        
        # Contributors
        contributors = order.get('contributors', {})
        if contributors:
            contrib_lines = []
            total_dp_contributed = sum(contributors.values())
            
            for user_id, points in sorted(contributors.items(), key=lambda x: -x[1])[:10]:
                contrib_lines.append(f"<@{user_id}>: **{points}** DP")
            
            if len(contributors) > 10:
                contrib_lines.append(f"*...and {len(contributors) - 10} more*")
            
            log_embed.add_field(
                name=f"👥 Contributors ({len(contributors)} members, {total_dp_contributed} total DP)",
                value="\n".join(contrib_lines),
                inline=False
            )
        
        # Timestamps
        created_at = order.get('created_at', '')
        if created_at:
            try:
                created_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                log_embed.add_field(
                    name="Created",
                    value=created_date.strftime('%Y-%m-%d %H:%M UTC'),
                    inline=True
                )
            except:
                pass
        
        log_embed.timestamp = datetime.utcnow()
        
        try:
            await log_channel.send(embed=log_embed)
        except Exception as e:
            logger.error(f"Failed to log work order completion: {e}")
    
    # =========================
    # SLASH COMMANDS
    # =========================
    
    @app_commands.command(name="artisan_setup", description="Create artisan economy control panel (Admin only)")
    @app_commands.default_permissions(administrator=True)
    async def setup_artisan(self, interaction: discord.Interaction):
        """Create the artisan control panel and treasury display"""
        await interaction.response.defer(ephemeral=True)
        
        # Get channels
        workorders_channel = self.bot.get_channel(ARTISAN_WORKORDERS_CHANNEL_ID)
        treasury_channel = self.bot.get_channel(ARTISAN_TREASURY_CHANNEL_ID)
        
        if not isinstance(workorders_channel, discord.TextChannel):
            await interaction.followup.send(
                "❌ Work orders channel not found. Check ARTISAN_WORKORDERS_CHANNEL_ID",
                ephemeral=True
            )
            return
        
        if not isinstance(treasury_channel, discord.TextChannel):
            await interaction.followup.send(
                "❌ Treasury channel not found. Check ARTISAN_TREASURY_CHANNEL_ID",
                ephemeral=True
            )
            return
        
        # Delete old embeds if they exist
        if self.control_panel_message_id:
            try:
                old_msg = await workorders_channel.fetch_message(self.control_panel_message_id)
                await old_msg.delete()
                logger.info("🗑️ Deleted old control panel during setup")
            except:
                pass
        
        if self.treasury_message_id:
            try:
                old_msg = await treasury_channel.fetch_message(self.treasury_message_id)
                await old_msg.delete()
                logger.info("🗑️ Deleted old treasury during setup")
            except:
                pass
        
        # Post fresh embeds
        await self.post_control_panel(workorders_channel)
        await self.post_treasury_embed(treasury_channel)
        
        await interaction.followup.send(
            f"✅ Control panel created in {workorders_channel.mention}\n"
            f"✅ Treasury display created in {treasury_channel.mention}",
            ephemeral=True
        )
    
    @app_commands.command(name="artisan_stats", description="View artisan economy statistics")
    async def artisan_stats(self, interaction: discord.Interaction):
        """Show artisan statistics"""
        await interaction.response.defer(ephemeral=True)
        
        embed = discord.Embed(
            title="📊 Artisan Economy Statistics",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="💰 Treasury",
            value=f"**{self.treasury_balance:,}** gold",
            inline=True
        )
        
        # Count active work orders
        active_orders = len([wo for wo in self.work_orders.values() if wo.get('status') == 'active'])
        
        embed.add_field(
            name="📋 Work Orders",
            value=f"{active_orders} active",
            inline=True
        )
        
        embed.add_field(
            name="👥 Contributors",
            value=str(len(self.donations)),
            inline=True
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="complete_workorder", description="Mark a work order as complete (Manager only)")
    @app_commands.describe(order_id="The work order ID to complete")
    async def complete_workorder(self, interaction: discord.Interaction, order_id: str):
        """Complete a work order"""
        # Check permissions
        manager_roles = ARTISAN_MANAGER_ROLE_IDS
        user_roles = [role.id for role in interaction.user.roles]
        
        has_permission = (
            interaction.user.guild_permissions.administrator or
            any(role_id in user_roles for role_id in manager_roles)
        )
        
        if not has_permission:
            await interaction.response.send_message(
                "❌ Only guild managers can complete work orders.",
                ephemeral=True
            )
            return
        
        order = self.work_orders.get(order_id)
        if not order:
            await interaction.response.send_message(
                f"❌ Work order `{order_id}` not found.",
                ephemeral=True
            )
            return
        
        if order.get('status') != 'active':
            await interaction.response.send_message(
                f"❌ This work order is already {order.get('status')}.",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        
        # Mark as complete
        order['status'] = 'completed'
        order['completed_at'] = datetime.utcnow().isoformat()
        order['completed_by'] = interaction.user.id
        
        # Award points to all contributors
        contributors = order.get('contributors', {})
        for user_id, points in contributors.items():
            if user_id not in self.donations:
                self.donations[user_id] = {
                    'total_points': 0,
                    'work_orders_completed': 0,
                    'materials_donated': {}
                }
            
            self.donations[user_id]['total_points'] += points
            self.donations[user_id]['work_orders_completed'] = \
                self.donations[user_id].get('work_orders_completed', 0) + 1
        
        self.save_data()
        
        # Update work order embed
        await self.update_work_order_embed(order_id)
        
        # Update control panel
        await self.update_control_panel()
        
        # Log to admin channel
        log_channel = self.bot.get_channel(ARTISAN_LOGS_CHANNEL_ID)
        if isinstance(log_channel, discord.TextChannel):
            log_embed = discord.Embed(
                title="✅ Work Order Completed",
                description=f"**{order.get('item_name')}** (ID: {order_id})",
                color=discord.Color.green()
            )
            log_embed.add_field(
                name="Completed By",
                value=f"<@{interaction.user.id}>",
                inline=True
            )
            log_embed.add_field(
                name="Contributors",
                value=str(len(contributors)),
                inline=True
            )
            log_embed.timestamp = datetime.utcnow()
            await log_channel.send(embed=log_embed)
        
        await interaction.followup.send(
            f"✅ Work order **{order.get('item_name')}** marked as complete!\n"
            f"Points awarded to {len(contributors)} contributor(s).",
            ephemeral=True
        )
    
    @app_commands.command(name="cancel_workorder", description="Cancel a work order (Manager only)")
    @app_commands.describe(order_id="The work order ID to cancel")
    async def cancel_workorder(self, interaction: discord.Interaction, order_id: str):
        """Cancel a work order"""
        # Check permissions
        manager_roles = ARTISAN_MANAGER_ROLE_IDS
        user_roles = [role.id for role in interaction.user.roles]
        
        has_permission = (
            interaction.user.guild_permissions.administrator or
            any(role_id in user_roles for role_id in manager_roles)
        )
        
        if not has_permission:
            await interaction.response.send_message(
                "❌ Only guild managers can cancel work orders.",
                ephemeral=True
            )
            return
        
        order = self.work_orders.get(order_id)
        if not order:
            await interaction.response.send_message(
                f"❌ Work order `{order_id}` not found.",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        
        # Mark as cancelled
        order['status'] = 'cancelled'
        order['cancelled_at'] = datetime.utcnow().isoformat()
        order['cancelled_by'] = interaction.user.id
        
        self.save_data()
        
        # Log detailed cancellation to admin channel
        await self.log_work_order_cancellation(order_id, interaction.user.id)
        
        # Delete the work order embed from the channel
        await self.delete_work_order_embed(order_id)
        
        # Update control panel
        await self.update_control_panel()
        
        await interaction.followup.send(
            f"✅ Work order `{order_id}` has been cancelled and removed from the channel.",
            ephemeral=True
        )
    
    @app_commands.command(name="searchworkorders", description="Search and view all active work orders")
    async def search_workorders(self, interaction: discord.Interaction):
        """Search through all active work orders"""
        # Get all active work orders
        active_orders = {
            order_id: order for order_id, order in self.work_orders.items()
            if order.get('status') == 'active'
        }
        
        if not active_orders:
            await interaction.response.send_message(
                "📋 No active work orders found.",
                ephemeral=True
            )
            return
        
        # Build embed showing all active orders
        embed = discord.Embed(
            title="🔍 Active Work Orders",
            description=f"Found **{len(active_orders)}** active work order(s)",
            color=discord.Color.blue()
        )
        
        # Add field for each work order (limit to first 10 for embed size)
        for i, (order_id, order) in enumerate(list(active_orders.items())[:10], 1):
            materials = order.get('materials', {})
            total_materials = len(materials)
            
            # Calculate overall progress
            total_needed = sum(mat.get('needed', 0) for mat in materials.values())
            total_donated = sum(mat.get('donated', 0) for mat in materials.values())
            progress = int((total_donated / total_needed) * 100) if total_needed > 0 else 0
            
            # Get material names (first 3)
            mat_names = list(materials.keys())[:3]
            mat_display = ", ".join(mat_names)
            if total_materials > 3:
                mat_display += f" (+{total_materials - 3} more)"
            
            embed.add_field(
                name=f"{i}. Order `{order_id}`",
                value=(
                    f"**Materials:** {mat_display}\n"
                    f"**Progress:** {progress}% ({total_donated}/{total_needed})\n"
                    f"**Contributors:** {len(order.get('contributors', {}))}"
                ),
                inline=False
            )
        
        if len(active_orders) > 10:
            embed.set_footer(text=f"Showing first 10 of {len(active_orders)} orders")
        
        # Add view with dropdown to select work order
        view = SearchWorkOrdersView(self, list(active_orders.keys())[:25])  # Discord limit is 25 options
        
        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True
        )


# =========================
# CONTROL PANEL VIEW
# =========================

class ArtisanControlView(discord.ui.View):
    """Main artisan control panel buttons"""
    def __init__(self, cog: ArtisanEconomy):
        super().__init__(timeout=None)
        self.cog = cog
    
    @discord.ui.button(label="Create Workorder", style=discord.ButtonStyle.primary, emoji="📋")
    async def create_workorder_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Create a new work order (Manager only)"""
        # Check permissions
        manager_roles = ARTISAN_MANAGER_ROLE_IDS
        user_roles = [role.id for role in interaction.user.roles]
        
        has_permission = (
            interaction.user.guild_permissions.administrator or
            any(role_id in user_roles for role_id in manager_roles)
        )
        
        if not has_permission:
            await interaction.response.send_message(
                "❌ Only guild managers can create work orders.",
                ephemeral=True
            )
            return
        
        # Open modal to create work order
        modal = CreateWorkOrderStep1Modal(self.cog)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="View My Donations", style=discord.ButtonStyle.secondary, emoji="📊")
    async def view_donations_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        
        if user_id not in self.cog.donations:
            await interaction.response.send_message(
                "📊 You haven't made any donations yet.\n\n"
                "Donate materials to work orders to start earning points!",
                ephemeral=True
            )
            return
        
        donations = self.cog.donations[user_id]
        total_points = donations.get('total_points', 0)
        donation_list = donations.get('donation_list', [])
        num_donations = len(donation_list)
        
        embed = discord.Embed(
            title="📊 Your Donation Statistics",
            color=discord.Color.green()
        )
        
        embed.add_field(
            name="Donation Points",
            value=f"**{total_points}** DP",
            inline=True
        )
        
        embed.add_field(
            name="Number of Donations",
            value=f"**{num_donations}**",
            inline=True
        )
        
        # Add "Show All Donations" button
        view = ShowAllDonationsView(self.cog, user_id)
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    
    @discord.ui.button(label="Misc Donation", style=discord.ButtonStyle.secondary, emoji="🎁")
    async def misc_donation_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Record miscellaneous donations (Manager only)"""
        # Check permissions
        manager_roles = ARTISAN_MANAGER_ROLE_IDS
        user_roles = [role.id for role in interaction.user.roles]
        
        has_permission = (
            interaction.user.guild_permissions.administrator or
            any(role_id in user_roles for role_id in manager_roles)
        )
        
        if not has_permission:
            await interaction.response.send_message(
                "❌ Only guild managers can record misc donations.",
                ephemeral=True
            )
            return
        
        # Show member selection view
        view = MiscDonationMemberSelectView(self.cog)
        await interaction.response.send_message(
            "Select the member who made the donation:",
            view=view,
            ephemeral=True
        )


# =========================
# SHOW ALL DONATIONS VIEW
# =========================

class ShowAllDonationsView(discord.ui.View):
    """View with button to show all donations"""
    def __init__(self, cog: ArtisanEconomy, user_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.user_id = user_id
    
    @discord.ui.button(label="Show All Donations", style=discord.ButtonStyle.primary)
    async def show_all_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        donations = self.cog.donations.get(self.user_id, {})
        donation_list = donations.get('donation_list', [])
        
        if not donation_list:
            await interaction.response.send_message(
                "No donations found.",
                ephemeral=True
            )
            return
        
        # Format donations list (no emojis, easy to read)
        lines = []
        for i, donation in enumerate(donation_list, 1):
            material = donation.get('material', 'Unknown')
            quantity = donation.get('quantity', 0)
            rarity = donation.get('rarity', 'Common')
            dp_value = donation.get('dp_value', 0)
            total_dp = donation.get('total_dp', quantity * dp_value)  # Calculate if not stored
            
            lines.append(f"{i}. {material} x{quantity} ({rarity}) - {total_dp} DP")
        
        # Split into chunks if too long (Discord has 2000 char limit per message)
        chunk_size = 30
        chunks = [lines[i:i + chunk_size] for i in range(0, len(lines), chunk_size)]
        
        for chunk_num, chunk in enumerate(chunks, 1):
            content = f"**Donations (Part {chunk_num}/{len(chunks)}):**\n```\n" + "\n".join(chunk) + "\n```"
            
            if chunk_num == 1:
                await interaction.response.send_message(content, ephemeral=True)
            else:
                await interaction.followup.send(content, ephemeral=True)


# =========================
# MISC DONATION MEMBER SELECT
# =========================

class MiscDonationMemberSelectView(discord.ui.View):
    """View to select member for misc donation"""
    def __init__(self, cog: ArtisanEconomy):
        super().__init__(timeout=60)
        self.cog = cog
        
        # Get all members with the opt-in role
        self.add_item(MiscDonationMemberSelect(cog))


class MiscDonationMemberSelect(discord.ui.UserSelect):
    """User select for choosing who made the donation"""
    def __init__(self, cog: ArtisanEconomy):
        self.cog = cog
        super().__init__(
            placeholder="Select the donating member",
            min_values=1,
            max_values=1
        )
    
    async def callback(self, interaction: discord.Interaction):
        selected_user = self.values[0]
        
        # Open modal for donation details, passing the original message for cleanup
        modal = MiscDonationModal(self.cog, selected_user.id, interaction.message)
        await interaction.response.send_modal(modal)


# =========================
# TREASURY MANAGEMENT VIEW
# =========================

class TreasuryManagementView(discord.ui.View):
    """Buttons for treasury management"""
    def __init__(self, cog: ArtisanEconomy):
        super().__init__(timeout=None)
        self.cog = cog
    
    @discord.ui.button(label="Deposit Gold", style=discord.ButtonStyle.success, emoji="💰")
    async def deposit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Deposit gold to treasury"""
        modal = DepositGoldModal(self.cog)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="Withdraw Gold", style=discord.ButtonStyle.danger, emoji="💸")
    async def withdraw_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Withdraw gold from treasury (Manager only)"""
        # Check if user has manager role
        manager_roles = ARTISAN_MANAGER_ROLE_IDS
        user_roles = [role.id for role in interaction.user.roles]
        
        has_permission = (
            interaction.user.guild_permissions.administrator or
            any(role_id in user_roles for role_id in manager_roles)
        )
        
        if not has_permission:
            await interaction.response.send_message(
                "❌ Only guild managers can withdraw from the treasury.",
                ephemeral=True
            )
            return
        
        modal = WithdrawGoldModal(self.cog)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="Transaction History", style=discord.ButtonStyle.secondary, emoji="📜")
    async def history_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show full transaction history"""
        if not self.cog.treasury_transactions:
            await interaction.response.send_message(
                "📜 No transaction history yet.",
                ephemeral=True
            )
            return
        
        # Show last 50 transactions
        transactions = self.cog.treasury_transactions[-50:]
        
        embed = discord.Embed(
            title="📜 Treasury Transaction History",
            description=f"**Current Balance:** {self.cog.treasury_balance:,} gold",
            color=discord.Color.blue()
        )
        
        transaction_text = []
        for txn in reversed(transactions):
            amount = txn.get('amount', 0)
            desc = txn.get('description', 'Unknown')
            date_str = txn.get('date', '')
            user_id = txn.get('user_id')
            
            # Format date
            try:
                date_obj = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                date_display = date_obj.strftime('%Y-%m-%d %H:%M')
            except:
                date_display = date_str[:16] if len(date_str) >= 16 else date_str
            
            sign = "+" if amount > 0 else ""
            user_mention = f"<@{user_id}>" if user_id else "System"
            transaction_text.append(f"`{date_display}` {sign}{amount:,}g - {desc} ({user_mention})")
        
        # Split into multiple embeds if too long
        if len(transaction_text) > 25:
            embed.description += f"\n\nShowing last 25 of {len(transactions)} transactions"
            embed.add_field(
                name="Recent Transactions",
                value="\n".join(transaction_text[:25]),
                inline=False
            )
        else:
            embed.add_field(
                name="All Transactions",
                value="\n".join(transaction_text),
                inline=False
            )
        
        embed.set_footer(text=f"Total transactions: {len(self.cog.treasury_transactions)}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


# =========================
# TREASURY MODALS
# =========================

class DepositGoldModal(discord.ui.Modal, title="Deposit Gold to Treasury"):
    """Modal for depositing gold"""
    
    def __init__(self, cog: ArtisanEconomy):
        super().__init__()
        self.cog = cog
        
        self.amount = discord.ui.TextInput(
            label="Amount",
            placeholder="How much gold are you depositing?",
            required=True,
            max_length=10
        )
        
        self.note = discord.ui.TextInput(
            label="Note",
            placeholder="What is this deposit for?",
            required=True,
            style=discord.TextStyle.paragraph,
            max_length=200
        )
        
        self.add_item(self.amount)
        self.add_item(self.note)
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Parse amount
        try:
            amount = int(self.amount.value.strip().replace(',', ''))
            if amount <= 0:
                raise ValueError("Amount must be positive")
        except ValueError:
            await interaction.followup.send(
                "❌ Invalid amount. Please enter a positive number.",
                ephemeral=True
            )
            return
        
        note = self.note.value.strip()
        
        # Record transaction
        self.cog.treasury_balance += amount
        
        transaction = {
            'amount': amount,
            'description': note,
            'user_id': interaction.user.id,
            'date': datetime.utcnow().isoformat(),
            'type': 'deposit'
        }
        
        self.cog.treasury_transactions.append(transaction)
        self.cog.save_data()
        
        # Update treasury embed
        await self.cog.update_treasury_embed()
        
        # Log to admin channel
        log_channel = self.cog.bot.get_channel(ARTISAN_LOGS_CHANNEL_ID)
        if isinstance(log_channel, discord.TextChannel):
            log_embed = discord.Embed(
                title="💰 Gold Deposited",
                description=f"**+{amount:,} gold** deposited to treasury",
                color=discord.Color.green()
            )
            log_embed.add_field(name="By", value=f"<@{interaction.user.id}>", inline=True)
            log_embed.add_field(name="New Balance", value=f"{self.cog.treasury_balance:,}g", inline=True)
            log_embed.add_field(name="Note", value=note, inline=False)
            log_embed.timestamp = datetime.utcnow()
            await log_channel.send(embed=log_embed)
        
        await interaction.followup.send(
            f"✅ **Deposit recorded!**\n\n"
            f"Amount: **{amount:,} gold**\n"
            f"New balance: **{self.cog.treasury_balance:,} gold**\n"
            f"Note: {note}",
            ephemeral=True
        )


class WithdrawGoldModal(discord.ui.Modal, title="Withdraw Gold from Treasury"):
    """Modal for withdrawing gold (Manager only)"""
    
    def __init__(self, cog: ArtisanEconomy):
        super().__init__()
        self.cog = cog
        
        self.amount = discord.ui.TextInput(
            label="Amount",
            placeholder="How much gold are you withdrawing?",
            required=True,
            max_length=10
        )
        
        self.reason = discord.ui.TextInput(
            label="Reason",
            placeholder="What is this withdrawal for?",
            required=True,
            style=discord.TextStyle.paragraph,
            max_length=200
        )
        
        self.add_item(self.amount)
        self.add_item(self.reason)
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Parse amount
        try:
            amount = int(self.amount.value.strip().replace(',', ''))
            if amount <= 0:
                raise ValueError("Amount must be positive")
        except ValueError:
            await interaction.followup.send(
                "❌ Invalid amount. Please enter a positive number.",
                ephemeral=True
            )
            return
        
        # Check if sufficient balance
        if amount > self.cog.treasury_balance:
            await interaction.followup.send(
                f"❌ Insufficient funds!\n\n"
                f"Requested: **{amount:,} gold**\n"
                f"Available: **{self.cog.treasury_balance:,} gold**",
                ephemeral=True
            )
            return
        
        reason = self.reason.value.strip()
        
        # Record transaction
        self.cog.treasury_balance -= amount
        
        transaction = {
            'amount': -amount,
            'description': reason,
            'user_id': interaction.user.id,
            'date': datetime.utcnow().isoformat(),
            'type': 'withdrawal'
        }
        
        self.cog.treasury_transactions.append(transaction)
        self.cog.save_data()
        
        # Update treasury embed
        await self.cog.update_treasury_embed()
        
        # Log to admin channel
        log_channel = self.cog.bot.get_channel(ARTISAN_LOGS_CHANNEL_ID)
        if isinstance(log_channel, discord.TextChannel):
            log_embed = discord.Embed(
                title="💸 Gold Withdrawn",
                description=f"**-{amount:,} gold** withdrawn from treasury",
                color=discord.Color.red()
            )
            log_embed.add_field(name="By", value=f"<@{interaction.user.id}>", inline=True)
            log_embed.add_field(name="New Balance", value=f"{self.cog.treasury_balance:,}g", inline=True)
            log_embed.add_field(name="Reason", value=reason, inline=False)
            log_embed.timestamp = datetime.utcnow()
            await log_channel.send(embed=log_embed)
        
        await interaction.followup.send(
            f"✅ **Withdrawal recorded!**\n\n"
            f"Amount: **{amount:,} gold**\n"
            f"New balance: **{self.cog.treasury_balance:,} gold**\n"
            f"Reason: {reason}",
            ephemeral=True
        )


# =========================
# MISC DONATION MODAL
# =========================

class MiscDonationModal(discord.ui.Modal, title="Record Misc Donation"):
    """Modal for recording misc donations"""
    
    def __init__(self, cog: ArtisanEconomy, donating_user_id: int, original_message: discord.Message | None = None):
        super().__init__()
        self.cog = cog
        self.donating_user_id = donating_user_id
        self.original_message = original_message
        
        self.material = discord.ui.TextInput(
            label="Material/Item",
            placeholder="e.g., Iron Ore",
            required=True,
            max_length=100
        )
        
        self.quantity = discord.ui.TextInput(
            label="Quantity",
            placeholder="e.g., 100",
            required=True,
            max_length=10
        )
        
        self.rarity = discord.ui.TextInput(
            label="Rarity",
            placeholder="e.g., Common, Rare, Epic",
            required=True,
            max_length=50
        )
        
        self.dp_value = discord.ui.TextInput(
            label="DP Value",
            placeholder="e.g., 10",
            required=True,
            max_length=10
        )
        
        self.add_item(self.material)
        self.add_item(self.quantity)
        self.add_item(self.rarity)
        self.add_item(self.dp_value)
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Parse quantity
        try:
            qty = int(self.quantity.value.strip())
            if qty <= 0:
                raise ValueError("Quantity must be positive")
        except ValueError:
            await interaction.followup.send(
                "❌ Invalid quantity. Please enter a positive number.",
                ephemeral=True
            )
            return
        
        # Parse DP value
        try:
            dp = int(self.dp_value.value.strip())
            if dp < 0:
                raise ValueError("DP value must be non-negative")
        except ValueError:
            await interaction.followup.send(
                "❌ Invalid DP value. Please enter a non-negative number.",
                ephemeral=True
            )
            return
        
        # Normalize material name and rarity to title case for consistency
        material = self.material.value.strip().title()
        rarity = self.rarity.value.strip().title()
        
        # Calculate total DP (quantity * dp_value per item)
        total_dp = qty * dp
        
        # Track donation
        user_id = str(self.donating_user_id)
        if user_id not in self.cog.donations:
            self.cog.donations[user_id] = {
                'total_points': 0,
                'donation_list': []
            }
        
        # Add donation to list
        donation_entry = {
            'material': material,
            'quantity': qty,
            'rarity': rarity,
            'dp_value': dp,
            'total_dp': total_dp,
            'date': datetime.utcnow().isoformat(),
            'recorded_by': interaction.user.id
        }
        
        self.cog.donations[user_id]['donation_list'].append(donation_entry)
        self.cog.donations[user_id]['total_points'] += total_dp
        
        self.cog.save_data()
        
        # Log to admin channel
        log_channel = self.cog.bot.get_channel(ARTISAN_LOGS_CHANNEL_ID)
        if isinstance(log_channel, discord.TextChannel):
            log_embed = discord.Embed(
                title="Miscellaneous Donation Recorded",
                color=discord.Color.purple()
            )
            log_embed.add_field(name="Member", value=f"<@{self.donating_user_id}>", inline=True)
            log_embed.add_field(name="Recorded By", value=f"<@{interaction.user.id}>", inline=True)
            log_embed.add_field(name="Material", value=material, inline=False)
            log_embed.add_field(name="Quantity", value=str(qty), inline=True)
            log_embed.add_field(name="Rarity", value=rarity, inline=True)
            log_embed.add_field(name="DP per Item", value=f"{dp} DP", inline=True)
            log_embed.add_field(name="Total DP", value=f"+{total_dp} DP", inline=True)
            log_embed.timestamp = datetime.utcnow()
            await log_channel.send(embed=log_embed)
        
        await interaction.followup.send(
            f"✅ **Misc donation recorded for <@{self.donating_user_id}>!**\n\n"
            f"Material: **{qty}x {material}** ({rarity})\n"
            f"DP per item: **{dp} DP**\n"
            f"Total DP earned: **+{total_dp} DP**\n"
            f"New total: **{self.cog.donations[user_id]['total_points']} DP**",
            ephemeral=True
        )
        
        # Clean up the original member selection ephemeral
        if self.original_message is not None:
            try:
                await self.original_message.edit(
                    content=f"✅ Misc donation recorded for <@{self.donating_user_id}>",
                    view=None
                )
            except Exception:
                pass  # Message already dismissed or gone


# =========================
# CREATE WORK ORDER - STEP 1
# =========================

class CreateWorkOrderStep1Modal(discord.ui.Modal, title="Create Work Order"):
    """First modal: Ask for number of listings only"""
    
    def __init__(self, cog: ArtisanEconomy):
        super().__init__()
        self.cog = cog
        
        self.num_listings = discord.ui.TextInput(
            label="Number of Material Listings",
            placeholder="How many materials? (Max 5)",
            required=True,
            max_length=1
        )
        
        self.add_item(self.num_listings)
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Parse number of listings
        try:
            num_listings = int(self.num_listings.value.strip())
            if num_listings <= 0:
                raise ValueError("Number of listings must be positive")
            if num_listings > 5:
                raise ValueError("Maximum 5 listings per work order")
        except ValueError as e:
            await interaction.followup.send(
                f"❌ Invalid number of listings. {str(e)}",
                ephemeral=True
            )
            return
        
        # Store work order data temporarily
        temp_order = {
            'num_listings': num_listings,
            'materials': [],
            'created_by': interaction.user.id,
            'created_at': datetime.utcnow().isoformat()
        }
        
        # Start collecting listings
        await interaction.followup.send(
            f"Creating work order with {num_listings} material listing(s)...",
            ephemeral=True
        )
        
        # Send a message with button to start entering listings
        view = StartListingEntryView(self.cog, temp_order, 1)
        await interaction.followup.send(
            f"Click below to enter listing 1 of {num_listings}:",
            view=view,
            ephemeral=True
        )


class StartListingEntryView(discord.ui.View):
    """View with button to start entering a listing"""
    def __init__(self, cog: ArtisanEconomy, temp_order: dict, listing_num: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.temp_order = temp_order
        self.listing_num = listing_num
    
    @discord.ui.button(label="Enter Listing", style=discord.ButtonStyle.primary)
    async def enter_listing_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = CreateWorkOrderListingModal(self.cog, self.temp_order, self.listing_num)
        await interaction.response.send_modal(modal)


class CreateWorkOrderListingModal(discord.ui.Modal):
    """Modal for entering one material listing"""
    
    VALID_RARITIES = ["Common", "Uncommon", "Rare", "Heroic", "Epic", "Legendary"]
    
    def __init__(self, cog: ArtisanEconomy, temp_order: dict, listing_num: int):
        self.cog = cog
        self.temp_order = temp_order
        self.listing_num = listing_num
        
        super().__init__(title=f"Listing {listing_num}/{temp_order['num_listings']}")
        
        self.material = discord.ui.TextInput(
            label="Material/Item",
            placeholder="e.g., Iron Ore",
            required=True,
            max_length=100
        )
        
        self.rarity = discord.ui.TextInput(
            label="Rarity",
            placeholder="Common, Uncommon, Rare, Heroic, Epic, Legendary",
            required=True,
            max_length=20
        )
        
        self.quantity = discord.ui.TextInput(
            label="Quantity",
            placeholder="e.g., 100",
            required=True,
            max_length=10
        )
        
        self.dp_per_item = discord.ui.TextInput(
            label="Donation Points Per Item",
            placeholder="e.g., 2",
            required=True,
            max_length=10
        )
        
        # Add in correct order
        self.add_item(self.material)
        self.add_item(self.rarity)
        self.add_item(self.quantity)
        self.add_item(self.dp_per_item)
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Normalize material name to title case for consistency
        material = self.material.value.strip().title()
        # Normalize rarity to title case
        rarity = self.rarity.value.strip().title()
        
        # Validate rarity
        if rarity not in self.VALID_RARITIES:
            await interaction.followup.send(
                f"❌ Invalid rarity: `{rarity}`\n\n"
                f"Valid options: {', '.join(self.VALID_RARITIES)}",
                ephemeral=True
            )
            return
        
        # Parse quantity
        try:
            qty = int(self.quantity.value.strip())
            if qty <= 0:
                raise ValueError("Quantity must be positive")
        except ValueError:
            await interaction.followup.send(
                "❌ Invalid quantity. Please enter a positive number.",
                ephemeral=True
            )
            return
        
        # Parse DP per item
        try:
            dp_per_item = int(self.dp_per_item.value.strip())
            if dp_per_item < 0:
                raise ValueError("DP per item must be non-negative")
        except ValueError:
            await interaction.followup.send(
                "❌ Invalid DP per item. Please enter a non-negative number.",
                ephemeral=True
            )
            return
        
        # Add listing to temp order
        self.temp_order['materials'].append({
            'material': material,
            'quantity': qty,
            'rarity': rarity,
            'dp_per_item': dp_per_item,
            'donated': 0
        })
        
        # Check if we need more listings
        if self.listing_num < self.temp_order['num_listings']:
            # More listings needed
            next_num = self.listing_num + 1
            view = StartListingEntryView(self.cog, self.temp_order, next_num)
            await interaction.followup.send(
                f"✅ Listing {self.listing_num} added: {qty}x {material} ({rarity}) - {dp_per_item} DP per item\n\n"
                f"Click below to enter listing {next_num} of {self.temp_order['num_listings']}:",
                view=view,
                ephemeral=True
            )
        else:
            # All listings collected, create work order
            await self.create_work_order(interaction)
    
    async def create_work_order(self, interaction: discord.Interaction):
        """Create the work order with all collected listings"""
        order_id = self.cog.generate_order_id()
        
        # Convert materials list to dict format
        # Use material name + rarity as key to allow same material with different rarities
        materials_dict = {}
        for mat in self.temp_order['materials']:
            # Create unique key: "Material Name (Rarity)"
            material_key = f"{mat['material']} ({mat['rarity']})"
            materials_dict[material_key] = {
                'needed': mat['quantity'],
                'donated': 0,
                'rarity': mat['rarity'],
                'dp_per_item': mat['dp_per_item']
            }
        
        self.cog.work_orders[order_id] = {
            'order_id': order_id,
            'materials': materials_dict,
            'contributors': {},
            'status': 'active',
            'created_by': self.temp_order['created_by'],
            'created_at': self.temp_order['created_at']
        }
        
        self.cog.save_data()
        
        # Post work order embed
        await self.cog.post_work_order_embed(order_id)
        
        # Update control panel
        await self.cog.update_control_panel()
        
        # Log to admin channel
        log_channel = self.cog.bot.get_channel(ARTISAN_LOGS_CHANNEL_ID)
        if isinstance(log_channel, discord.TextChannel):
            log_embed = discord.Embed(
                title="Work Order Created",
                description=f"**Order ID:** `{order_id}`",
                color=discord.Color.blue()
            )
            log_embed.add_field(
                name="Created By",
                value=f"<@{self.temp_order['created_by']}>",
                inline=True
            )
            log_embed.add_field(
                name="Number of Listings",
                value=str(len(materials_dict)),
                inline=True
            )
            
            mat_list = []
            for mat_name, mat_data in materials_dict.items():
                mat_list.append(
                    f"{mat_name}: {mat_data['needed']} ({mat_data['rarity']}) - {mat_data['dp_per_item']} DP/item"
                )
            log_embed.add_field(
                name="Materials Required",
                value="\n".join(mat_list),
                inline=False
            )
            log_embed.timestamp = datetime.utcnow()
            await log_channel.send(embed=log_embed)
        
        await interaction.followup.send(
            f"✅ **Work order created!**\n\n"
            f"Order ID: `{order_id}`\n"
            f"Materials: {len(materials_dict)} listings\n\n"
            f"The work order has been posted in the work orders channel.",
            ephemeral=True
        )


# =========================
# DONATION FLOW VIEWS
# =========================

class MaterialSelectView(discord.ui.View):
    """View for selecting which material to donate"""
    def __init__(self, cog: ArtisanEconomy, order_id: str):
        super().__init__(timeout=60)
        self.cog = cog
        self.order_id = order_id
        
        # Add material select dropdown
        self.add_item(MaterialSelect(cog, order_id))


class MaterialSelect(discord.ui.Select):
    """Select dropdown for choosing material"""
    def __init__(self, cog: ArtisanEconomy, order_id: str):
        super().__init__(
            placeholder="Select which material to donate:",
            min_values=1,
            max_values=1
        )
        self.cog = cog
        self.order_id = order_id

        order = cog.work_orders.get(order_id)
        materials = order.get('materials', {}) if order else {}

        # Create options for each material
        options = []
        for mat_name, mat_data in materials.items():
            rarity = mat_data.get('rarity', 'Common')
            needed = mat_data.get('needed', 0)
            donated = mat_data.get('donated', 0)
            remaining = max(0, needed - donated)

            # Only show materials that still need donations
            if remaining > 0:
                options.append(
                    discord.SelectOption(
                        label=mat_name,
                        description=f"[{rarity}] - {remaining} remaining",
                        value=mat_name
                    )
                )

        if not options:
            options.append(
                discord.SelectOption(
                    label="All materials complete",
                    value="none",
                    description="No further donations required."
                )
            )

        self.options = options

    async def callback(self, interaction: discord.Interaction):
        selected_material = self.values[0]

        if selected_material == "none":
            # This is the only time we send a new ephemeral, because the flow ends here
            await interaction.response.edit_message(
                content="✅ All materials for this work order have been completed!",
                view=None
            )
            return

        # Build Step 2 view (recipient selection)
        guild = interaction.guild
        view = MemberSelectView(self.cog, self.order_id, selected_material, guild)

        # 🔁 EDIT the existing Step 1 ephemeral instead of sending a new one
        await interaction.response.edit_message(
            content=f"**Step 2:** Select the **recipient** for this donation (**{selected_material}**):",
            view=view
        )


class MemberSelectView(discord.ui.View):
    """View for selecting who is receiving the donation"""
    def __init__(self, cog: ArtisanEconomy, order_id: str, material: str, guild: discord.Guild | None):
        super().__init__(timeout=60)
        self.cog = cog
        self.order_id = order_id
        self.material = material
        self.material_name = material  # 👈 add this line

        ARTISAN_MANAGER_ROLE = 1448277106223222804

        if guild is None:
            logger.error("Guild not found when building MemberSelectView (guild was None)")
            return

        # Pull ONLY people with the specific role
        managers = [
            m for m in guild.members
            if any(r.id == ARTISAN_MANAGER_ROLE for r in m.roles)
        ]

        # Build dropdown options
        options = [
            discord.SelectOption(
                label=m.display_name,
                value=str(m.id),
                description="Donation recipient"
            )
            for m in managers
        ]

        if not options:
            options = [
                discord.SelectOption(
                    label="No eligible recipients found",
                    value="none",
                    default=True
                )
            ]

        # Single dropdown: role-filtered recipient selector
        self.add_item(RecipientDropdown(options, self))


class RecipientDropdown(discord.ui.Select):
    def __init__(self, options, parent_view):
        super().__init__(
            placeholder="Select donation recipient",
            options=options,
            min_values=1,
            max_values=1,
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        # Safety "none" option
        if self.values[0] == "none":
            await interaction.response.edit_message(
                content="❌ No valid recipients available.",
                view=None,
            )
            return

        recipient_id = int(self.values[0])

        # Open the quantity modal and pass the current Step-2 ephemeral message
        modal = DonationQuantityModal(
            cog=self.parent_view.cog,
            order_id=self.parent_view.order_id,
            material_name=self.parent_view.material_name,
            donor_id=interaction.user.id,
            recorder_id=recipient_id,
            original_message=interaction.message,  # 👈 Step-2 ephemeral
        )

        await interaction.response.send_modal(modal)


class MemberSelect(discord.ui.UserSelect):
    """User select for choosing who made the donation"""
    def __init__(self, cog: ArtisanEconomy, order_id: str, material: str):
        self.cog = cog
        self.order_id = order_id
        self.material = material
        
        super().__init__(
            placeholder="Select the member who is donating...",
            min_values=1,
            max_values=1
        )
    
    async def callback(self, interaction: discord.Interaction):
        selected_member = self.values[0]
        
        # Check if member has opt-in role
        opt_in_role = interaction.guild.get_role(ARTISAN_OPTIN_ROLE_ID)
        if opt_in_role and opt_in_role not in selected_member.roles:
            await interaction.response.send_message(
                f"❌ {selected_member.mention} does not have the required opt-in role.",
                ephemeral=True
            )
            return
        
        # Show quantity modal
        modal = DonationQuantityModal(
            self.cog,
            self.order_id,
            self.material,
            selected_member.id,
            interaction.user.id  # Manager who is recording this
        )
        await interaction.response.send_modal(modal)


class DonationQuantityModal(discord.ui.Modal, title="Enter Donation Amount"):
    """Modal for entering donation quantity (donor side)"""

    def __init__(
        self,
        cog: "ArtisanEconomy",
        order_id: str,
        material_name: str,
        donor_id: int,
        recorder_id: int,
        original_message: discord.Message | None = None,  # Step-2 ephemeral
    ):
        super().__init__()

        self.cog = cog
        self.order_id = order_id
        self.material_name = material_name
        self.donor_id = donor_id
        self.recorder_id = recorder_id
        self.original_message = original_message

        self.quantity = discord.ui.TextInput(
            label="Quantity",
            placeholder="How many are you donating?",
            required=True,
            max_length=10,
        )
        self.add_item(self.quantity)

    async def on_submit(self, interaction: discord.Interaction):
        # --- Parse quantity ---
        try:
            qty = int(self.quantity.value.strip())
            if qty <= 0:
                raise ValueError("Quantity must be positive")
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid quantity. Please enter a positive whole number.",
                ephemeral=True,
            )
            return

        # --- Validate work order & material / remaining amount ---
        order = self.cog.work_orders.get(self.order_id)
        if not order:
            await interaction.response.send_message(
                "❌ Work order not found.", ephemeral=True
            )
            return

        material_data = order.get("materials", {}).get(self.material_name)
        if not material_data:
            await interaction.response.send_message(
                "❌ That material is not part of this work order.",
                ephemeral=True,
            )
            return

        needed = material_data.get("needed", 0)
        donated = material_data.get("donated", 0)
        remaining = max(0, needed - donated)

        if qty > remaining:
            await interaction.response.send_message(
                f"❌ Quantity ({qty}) exceeds remaining needed ({remaining}).",
                ephemeral=True,
            )
            return

        # --- Send DM to the selected Artisan Manager for confirmation ---
        await self.cog.send_donation_confirmation(
            interaction=interaction,
            donor_id=self.donor_id,
            recipient_id=self.recorder_id,
            order_id=self.order_id,
            material_name=self.material_name,
            quantity=qty,
        )

        # ✅ Send simple ephemeral confirmation to the donor
        if not interaction.response.is_done():
            await interaction.response.send_message(
                f"✅ Your donation request for **{qty}× {self.material_name}** "
                f"has been submitted to <@{self.recorder_id}> for approval.",
                ephemeral=True,
            )

        # --- Update the old Step-2 ephemeral so it no longer shows the dropdown ---
        if self.original_message is not None:
            try:
                await self.original_message.edit(
                    content=(
                        f"✅ Sent a donation approval request for **{qty}× {self.material_name}** "
                        f"to <@{self.recorder_id}>."
                    ),
                    view=None,  # removes the recipient dropdown
                )
            except Exception:
                pass  # message already dismissed or gone


class DonationConfirmationView(discord.ui.View):
    """DM view for confirming / declining / editing a donation."""
    def __init__(self, cog, order_id: str, material_name: str, quantity: int, donor_id: int, recorder_id: int):
        super().__init__(timeout=600)
        self.cog = cog
        self.order_id = order_id
        self.material_name = material_name
        self.material = material_name  # for compatibility with older code
        self.quantity = quantity
        self.donor_id = donor_id
        self.recorder_id = recorder_id

    # ✅ CONFIRM
    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Confirm the donation and update the work order / DP."""
        if interaction.user.id != self.recorder_id:
            await interaction.response.send_message(
                "❌ Only the manager who recorded this donation can confirm it.",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        # Look up work order
        order = self.cog.work_orders.get(self.order_id)
        if not order:
            await interaction.followup.send("❌ Work order no longer exists.", ephemeral=True)
            return

        material_data = order.get("materials", {}).get(self.material_name)
        if not material_data:
            await interaction.followup.send("❌ Material not found on this work order.", ephemeral=True)
            return

        # Update donated amount
        material_data["donated"] = material_data.get("donated", 0) + self.quantity

        # Calculate DP
        dp_per_item = material_data.get("dp_per_item", 0)
        total_dp = self.quantity * dp_per_item

        # Track donor points
        donor_id_str = str(self.donor_id)

        # Make sure this donor has a record, and that it has both fields
        donor_record = self.cog.donations.get(donor_id_str)
        if donor_record is None:
            donor_record = {"total_points": 0, "donation_list": []}
        else:
            # Backwards-compat: older data might be missing one or both keys
            if "total_points" not in donor_record:
                donor_record["total_points"] = 0
            if "donation_list" not in donor_record:
                donor_record["donation_list"] = []

        # Save back to the main dict
        self.cog.donations[donor_id_str] = donor_record

        # Apply this donation
        donor_record["total_points"] += total_dp
        donor_record["donation_list"].append({
            "material": self.material_name,
            "quantity": self.quantity,
            "rarity": material_data.get("rarity", "Common"),
            "dp_per_item": dp_per_item,
            "total_dp": total_dp,
            "work_order_id": self.order_id,
            "date": datetime.utcnow().isoformat(),
            "recorded_by": self.recorder_id
        })


        # Update contributors on the work order
        if "contributors" not in order:
            order["contributors"] = {}
        order["contributors"][donor_id_str] = order["contributors"].get(donor_id_str, 0) + total_dp

        # Persist & refresh work order embed in the channel
        self.cog.save_data()
        await self.cog.update_work_order_embed(self.order_id)

        # Update the DM message to show success
        success_embed = discord.Embed(
            title="✅ Donation Confirmed",
            description=f"Work Order: `{self.order_id}`",
            colour=discord.Colour.green()
        )
        success_embed.add_field(name="Material", value=self.material_name, inline=True)
        success_embed.add_field(name="Quantity", value=str(self.quantity), inline=True)
        success_embed.add_field(name="DP Earned", value=f"+{total_dp} DP", inline=True)
        success_embed.add_field(
            name="Your Total DP",
            value=f"{self.cog.donations[donor_id_str]['total_points']} DP",
            inline=False
        )

        try:
            await interaction.message.edit(embed=success_embed, view=None)
        except discord.NotFound:
            # DM deleted by the user – nothing more to do
            pass

        # Log to admin / artisan logs channel
        log_channel = self.cog.bot.get_channel(ARTISAN_LOGS_CHANNEL_ID)
        if isinstance(log_channel, discord.TextChannel):
            log_embed = discord.Embed(
                title="Work Order Donation Confirmed",
                colour=discord.Colour.green()
            )
            log_embed.add_field(name="Donor", value=f"<@{self.donor_id}>", inline=True)
            log_embed.add_field(name="Recorded By", value=f"<@{self.recorder_id}>", inline=True)
            log_embed.add_field(name="Work Order", value=f"`{self.order_id}`", inline=False)
            log_embed.add_field(
                name="Material",
                value=f"{self.material_name} ({material_data.get('rarity', 'Unknown')})",
                inline=True
            )
            log_embed.add_field(name="Quantity", value=str(self.quantity), inline=True)
            log_embed.add_field(name="DP Earned", value=f"+{total_dp} DP", inline=True)
            log_embed.timestamp = datetime.utcnow()
            await log_channel.send(embed=log_embed)

    # ❌ DECLINE
    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, emoji="🛑")
    async def decline_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Decline the donation request – nothing is recorded."""
        if interaction.user.id != self.recorder_id:
            await interaction.response.send_message(
                "❌ Only the manager who recorded this donation can decline it.",
                ephemeral=True
            )
            return

        # Delete the confirmation message and tell the user it was cancelled
        try:
            await interaction.message.delete()
        except discord.NotFound:
            pass

        await interaction.response.send_message(
            "❌ Donation cancelled. Nothing has been recorded.",
            ephemeral=True
        )

    # ✏️ EDIT
    @discord.ui.button(label="Edit", style=discord.ButtonStyle.secondary, emoji="✏️")
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        Let the manager adjust the quantity before confirming.
        We delete this DM and reopen the quantity modal.
        """
        if interaction.user.id != self.recorder_id:
            await interaction.response.send_message(
                "❌ Only the manager who recorded this donation can edit it.",
                ephemeral=True
            )
            return

        # Remove the old confirmation message
        try:
            await interaction.message.delete()
        except discord.NotFound:
            pass

        # Reopen the quantity modal so they can adjust the number
        modal = DonationQuantityModal(
            cog=self.cog,
            order_id=self.order_id,
            material_name=self.material_name,
            donor_id=self.donor_id,
            recorder_id=self.recorder_id,
        )
        await interaction.response.send_modal(modal)


class DonationEditView(discord.ui.View):
    def __init__(self, cog, order_id, material_name, quantity, recipient_id):
        super().__init__(timeout=120)
        self.cog = cog
        self.order_id = order_id
        self.material_name = material_name
        self.quantity = quantity
        self.recipient_id = recipient_id

    @discord.ui.button(label="Edit Quantity", style=discord.ButtonStyle.primary)
    async def edit_qty(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            DonationQuantityModal(
                self.cog,
                self.order_id,
                self.material_name,
                self.recipient_id
            )
        )

    @discord.ui.button(label="Edit Rarity", style=discord.ButtonStyle.secondary)
    async def edit_rarity(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            DonationRarityModal(
                self.cog,
                self.order_id,
                self.material_name,
                self.recipient_id
            )
        )


class EditDonationModal(discord.ui.Modal, title="Edit Donation Quantity"):
    """Modal for editing donation quantity"""
    
    def __init__(self, confirmation_view: DonationConfirmationView):
        super().__init__()
        self.confirmation_view = confirmation_view
        
        self.quantity = discord.ui.TextInput(
            label="New Quantity",
            placeholder=f"Current: {confirmation_view.quantity}",
            required=True,
            max_length=10,
            default=str(confirmation_view.quantity)
        )
        
        self.add_item(self.quantity)
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        # Parse new quantity
        try:
            new_qty = int(self.quantity.value.strip())
            if new_qty <= 0:
                raise ValueError("Quantity must be positive")
        except ValueError:
            await interaction.followup.send(
                "❌ Invalid quantity. Please enter a positive number.",
                ephemeral=True
            )
            return
        
        # Get order and check remaining
        order = self.confirmation_view.cog.work_orders.get(self.confirmation_view.order_id)
        if not order:
            await interaction.followup.send("❌ Work order not found.", ephemeral=True)
            return
        
        material_data = order.get('materials', {}).get(self.confirmation_view.material)
        if not material_data:
            await interaction.followup.send("❌ Material not found.", ephemeral=True)
            return
        
        needed = material_data.get('needed', 0)
        donated = material_data.get('donated', 0)
        remaining = max(0, needed - donated)
        
        if new_qty > remaining:
            await interaction.followup.send(
                f"❌ Quantity ({new_qty}) exceeds remaining needed ({remaining}).",
                ephemeral=True
            )
            return
        
        # Update confirmation view with new quantity
        self.confirmation_view.quantity = new_qty
        
        # Calculate new DP
        dp_per_item = material_data.get('dp_per_item', 0)
        new_total_dp = new_qty * dp_per_item
        rarity = material_data.get('rarity', 'Common')
        
        # Update embed
        updated_embed = discord.Embed(
            title="Donation Confirmation Required (Edited)",
            description=f"**Work Order:** `{self.confirmation_view.order_id}`",
            color=discord.Color.blue()
        )
        updated_embed.add_field(
            name="Material",
            value=f"{self.confirmation_view.material} ({rarity})",
            inline=True
        )
        updated_embed.add_field(
            name="Quantity",
            value=f"{new_qty} ✏️ (edited)",
            inline=True
        )
        updated_embed.add_field(
            name="DP Earned",
            value=f"{new_total_dp} DP",
            inline=True
        )
        updated_embed.add_field(
            name="Recorded By",
            value=f"<@{self.confirmation_view.recorder_id}>",
            inline=False
        )
        updated_embed.set_footer(text="Please confirm this donation is accurate")
        
        await interaction.message.edit(embed=updated_embed, view=self.confirmation_view)


# =========================
# WORK ORDER INTERACTION VIEW
# =========================

class WorkOrderView(discord.ui.View):
    """Buttons for interacting with work orders"""
    def __init__(self, cog: ArtisanEconomy, order_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.order_id = order_id
        
        # Check if order is complete (all materials fulfilled)
        order = cog.work_orders.get(order_id)
        is_complete = False
        
        if order and order.get('status') == 'active':
            materials = order.get('materials', {})
            if materials:
                is_complete = all(
                    mat_data.get('donated', 0) >= mat_data.get('needed', 0)
                    for mat_data in materials.values()
                )
        
        # Add donate and view details buttons (always present)
        self.add_item(self.DonateButton())
        self.add_item(self.DetailsButton())
        
        # Add either Complete or Cancel button based on status
        if is_complete:
            self.add_item(self.CompleteButton())
        else:
            self.add_item(self.CancelButton())
    
    class DonateButton(discord.ui.Button):
        def __init__(self):
            super().__init__(
                label="Donate Materials",
                style=discord.ButtonStyle.success,
                emoji="📦"
            )
        
        async def callback(self, interaction: discord.Interaction):
            view: WorkOrderView = self.view
            order = view.cog.work_orders.get(view.order_id)
            if not order:
                await interaction.response.send_message(
                    "❌ This work order no longer exists.",
                    ephemeral=True
                )
                return
            
            if order.get('status') != 'active':
                await interaction.response.send_message(
                    f"❌ This work order is {order.get('status')} and no longer accepting donations.",
                    ephemeral=True
                )
                return
            
            # Show material selection view
            material_view = MaterialSelectView(view.cog, view.order_id)
            await interaction.response.send_message(
                "**Step 1:** Select which material to donate:",
                view=material_view,
                ephemeral=True
            )
    
    class DetailsButton(discord.ui.Button):
        def __init__(self):
            super().__init__(
                label="View Details",
                style=discord.ButtonStyle.secondary,
                emoji="ℹ️"
            )
        
        async def callback(self, interaction: discord.Interaction):
            view: WorkOrderView = self.view
            order = view.cog.work_orders.get(view.order_id)
            if not order:
                await interaction.response.send_message(
                    "❌ This work order no longer exists.",
                    ephemeral=True
                )
                return
            
            embed = discord.Embed(
                title=f"📋 Work Order Details: {order.get('item_name')}",
                color=discord.Color.blue()
            )
            
            embed.add_field(
                name="Order ID",
                value=f"`{view.order_id}`",
                inline=True
            )
            
            embed.add_field(
                name="Status",
                value=order.get('status', 'active').title(),
                inline=True
            )
            
            embed.add_field(
                name="Quantity",
                value=str(order.get('quantity', 0)),
                inline=True
            )
            
            # Detailed materials breakdown
            materials = order.get('materials', {})
            if materials:
                mat_lines = []
                for mat_name, mat_data in materials.items():
                    needed = mat_data.get('needed', 0)
                    donated = mat_data.get('donated', 0)
                    remaining = max(0, needed - donated)
                    percent = int((donated / needed) * 100) if needed > 0 else 0
                    
                    mat_lines.append(
                        f"**{mat_name}**\n"
                        f"  ├ Needed: {needed}\n"
                        f"  ├ Donated: {donated}\n"
                        f"  ├ Remaining: {remaining}\n"
                        f"  └ Progress: {percent}%"
                    )
                
                embed.add_field(
                    name="📦 Material Breakdown",
                    value="\n\n".join(mat_lines),
                    inline=False
                )
            
            # All contributors
            contributors = order.get('contributors', {})
            if contributors:
                contrib_lines = []
                for user_id, points in sorted(contributors.items(), key=lambda x: -x[1]):
                    contrib_lines.append(f"<@{user_id}>: **{points}** points")
                
                embed.add_field(
                    name=f"👥 All Contributors ({len(contributors)})",
                    value="\n".join(contrib_lines[:10]),  # Show top 10
                    inline=False
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    class CompleteButton(discord.ui.Button):
        def __init__(self):
            super().__init__(
                label="Complete Work Order",
                style=discord.ButtonStyle.success,
                emoji="✅"
            )
        
        async def callback(self, interaction: discord.Interaction):
            """Complete this work order (Manager only)"""
            view: WorkOrderView = self.view
            
            # Check permissions
            manager_roles = ARTISAN_MANAGER_ROLE_IDS
            user_roles = [role.id for role in interaction.user.roles]
            
            has_permission = (
                interaction.user.guild_permissions.administrator or
                any(role_id in user_roles for role_id in manager_roles)
            )
            
            if not has_permission:
                await interaction.response.send_message(
                    "❌ Only guild managers can complete work orders.",
                    ephemeral=True
                )
                return
            
            order = view.cog.work_orders.get(view.order_id)
            if not order:
                await interaction.response.send_message(
                    "❌ This work order no longer exists.",
                    ephemeral=True
                )
                return
            
            if order.get('status') != 'active':
                await interaction.response.send_message(
                    f"❌ This work order is already {order.get('status')}.",
                    ephemeral=True
                )
                return
            
            # Show confirmation view
            confirm_view = CompleteWorkOrderConfirmView(view.cog, view.order_id)
            
            # Get materials summary for confirmation message
            materials = order.get('materials', {})
            mat_summary = []
            for mat_name, mat_data in list(materials.items())[:3]:  # Show first 3
                mat_summary.append(f"• {mat_name}")
            
            if len(materials) > 3:
                mat_summary.append(f"• ...and {len(materials) - 3} more")
            
            contributors = order.get('contributors', {})
            
            await interaction.response.send_message(
                f"✅ **Ready to complete this work order?**\n\n"
                f"**Order ID:** `{view.order_id}`\n"
                f"**Materials:**\n" + "\n".join(mat_summary) + "\n"
                f"**Contributors:** {len(contributors)} member(s)\n\n"
                f"This will mark the order as complete and archive it.",
                view=confirm_view,
                ephemeral=True
            )
    
    class CancelButton(discord.ui.Button):
        def __init__(self):
            super().__init__(
                label="Cancel Work Order",
                style=discord.ButtonStyle.danger,
                emoji="❌"
            )
        
        async def callback(self, interaction: discord.Interaction):
            """Cancel this work order (Manager only)"""
            view: WorkOrderView = self.view
            
            # Check permissions
            manager_roles = ARTISAN_MANAGER_ROLE_IDS
            user_roles = [role.id for role in interaction.user.roles]
            
            has_permission = (
                interaction.user.guild_permissions.administrator or
                any(role_id in user_roles for role_id in manager_roles)
            )
            
            if not has_permission:
                await interaction.response.send_message(
                    "❌ Only guild managers can cancel work orders.",
                    ephemeral=True
                )
                return
            
            order = view.cog.work_orders.get(view.order_id)
            if not order:
                await interaction.response.send_message(
                    "❌ This work order no longer exists.",
                    ephemeral=True
                )
                return
            
            if order.get('status') != 'active':
                await interaction.response.send_message(
                    f"❌ This work order is already {order.get('status')}.",
                    ephemeral=True
                )
                return
            
            # Show confirmation view
            confirm_view = CancelWorkOrderConfirmView(view.cog, view.order_id)
            
            # Get materials summary for confirmation message
            materials = order.get('materials', {})
            mat_summary = []
            for mat_name, mat_data in list(materials.items())[:3]:  # Show first 3
                mat_summary.append(f"• {mat_name}")
            
            if len(materials) > 3:
                mat_summary.append(f"• ...and {len(materials) - 3} more")
            
            await interaction.response.send_message(
                f"⚠️ **Are you sure you want to cancel this work order?**\n\n"
                f"**Order ID:** `{view.order_id}`\n"
                f"**Materials:**\n" + "\n".join(mat_summary) + "\n\n"
                f"This action cannot be undone.",
                view=confirm_view,
                ephemeral=True
            )


# =========================
# SEARCH WORK ORDERS VIEW
# =========================

class SearchWorkOrdersView(discord.ui.View):
    """View for searching and managing work orders"""
    def __init__(self, cog: ArtisanEconomy, order_ids: list):
        super().__init__(timeout=300)
        self.cog = cog
        self.order_ids = order_ids
        
        # Add dropdown
        self.add_item(WorkOrderSelectDropdown(cog, order_ids))


class WorkOrderSelectDropdown(discord.ui.Select):
    """Dropdown for selecting a work order"""
    def __init__(self, cog: ArtisanEconomy, order_ids: list):
        self.cog = cog
        
        # Build options
        options = []
        for order_id in order_ids:
            order = cog.work_orders.get(order_id)
            if not order:
                continue
            
            materials = order.get('materials', {})
            total_needed = sum(mat.get('needed', 0) for mat in materials.values())
            total_donated = sum(mat.get('donated', 0) for mat in materials.values())
            progress = int((total_donated / total_needed) * 100) if total_needed > 0 else 0
            
            # Get first material name for description
            first_mat = list(materials.keys())[0] if materials else "No materials"
            mat_count = len(materials)
            
            description = f"{first_mat}"
            if mat_count > 1:
                description += f" +{mat_count - 1} more"
            description += f" • {progress}% complete"
            
            options.append(
                discord.SelectOption(
                    label=f"Order {order_id}",
                    description=description[:100],  # Discord limit
                    value=order_id
                )
            )
        
        super().__init__(
            placeholder="Select a work order to view or manage...",
            options=options,
            min_values=1,
            max_values=1
        )
    
    async def callback(self, interaction: discord.Interaction):
        selected_order_id = self.values[0]
        order = self.cog.work_orders.get(selected_order_id)
        
        if not order:
            await interaction.response.send_message(
                "❌ This work order no longer exists.",
                ephemeral=True
            )
            return
        
        # Build detailed embed
        embed = discord.Embed(
            title=f"📋 Work Order: `{selected_order_id}`",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="Status",
            value=order.get('status', 'active').title(),
            inline=True
        )
        
        # Materials breakdown
        materials = order.get('materials', {})
        if materials:
            mat_lines = []
            for mat_name, mat_data in materials.items():
                needed = mat_data.get('needed', 0)
                donated = mat_data.get('donated', 0)
                remaining = max(0, needed - donated)
                rarity = mat_data.get('rarity', 'Common')
                
                mat_lines.append(
                    f"**{mat_name}** ({rarity})\n"
                    f"  └ {donated}/{needed} ({remaining} remaining)"
                )
            
            embed.add_field(
                name="📦 Materials",
                value="\n".join(mat_lines),
                inline=False
            )
        
        # Contributors
        contributors = order.get('contributors', {})
        if contributors:
            contrib_lines = []
            for user_id, points in sorted(contributors.items(), key=lambda x: -x[1])[:5]:
                contrib_lines.append(f"<@{user_id}>: **{points}** DP")
            
            embed.add_field(
                name=f"👥 Top Contributors ({len(contributors)} total)",
                value="\n".join(contrib_lines),
                inline=False
            )
        
        # Check if user is manager for cancel option
        manager_roles = ARTISAN_MANAGER_ROLE_IDS
        user_roles = [role.id for role in interaction.user.roles]
        
        is_manager = (
            interaction.user.guild_permissions.administrator or
            any(role_id in user_roles for role_id in manager_roles)
        )
        
        # Create view with appropriate buttons
        view = WorkOrderDetailView(self.cog, selected_order_id, is_manager)
        
        await interaction.response.edit_message(
            embed=embed,
            view=view
        )


class WorkOrderDetailView(discord.ui.View):
    """View for work order details with action buttons"""
    def __init__(self, cog: ArtisanEconomy, order_id: str, is_manager: bool):
        super().__init__(timeout=300)
        self.cog = cog
        self.order_id = order_id
        
        # Always add back button
        self.add_item(BackToSearchButton(cog))
        
        # Add cancel button only if user is manager and order is active
        order = cog.work_orders.get(order_id)
        if is_manager and order and order.get('status') == 'active':
            self.add_item(CancelFromSearchButton(cog, order_id))


class BackToSearchButton(discord.ui.Button):
    """Button to go back to search results"""
    def __init__(self, cog: ArtisanEconomy):
        super().__init__(
            label="Back to Search",
            style=discord.ButtonStyle.secondary,
            emoji="◀️"
        )
        self.cog = cog
    
    async def callback(self, interaction: discord.Interaction):
        # Rebuild search view
        active_orders = {
            order_id: order for order_id, order in self.cog.work_orders.items()
            if order.get('status') == 'active'
        }
        
        if not active_orders:
            await interaction.response.edit_message(
                content="📋 No active work orders found.",
                embed=None,
                view=None
            )
            return
        
        # Build embed showing all active orders
        embed = discord.Embed(
            title="🔍 Active Work Orders",
            description=f"Found **{len(active_orders)}** active work order(s)",
            color=discord.Color.blue()
        )
        
        # Add field for each work order (limit to first 10)
        for i, (order_id, order) in enumerate(list(active_orders.items())[:10], 1):
            materials = order.get('materials', {})
            total_materials = len(materials)
            
            total_needed = sum(mat.get('needed', 0) for mat in materials.values())
            total_donated = sum(mat.get('donated', 0) for mat in materials.values())
            progress = int((total_donated / total_needed) * 100) if total_needed > 0 else 0
            
            mat_names = list(materials.keys())[:3]
            mat_display = ", ".join(mat_names)
            if total_materials > 3:
                mat_display += f" (+{total_materials - 3} more)"
            
            embed.add_field(
                name=f"{i}. Order `{order_id}`",
                value=(
                    f"**Materials:** {mat_display}\n"
                    f"**Progress:** {progress}% ({total_donated}/{total_needed})\n"
                    f"**Contributors:** {len(order.get('contributors', {}))}"
                ),
                inline=False
            )
        
        if len(active_orders) > 10:
            embed.set_footer(text=f"Showing first 10 of {len(active_orders)} orders")
        
        view = SearchWorkOrdersView(self.cog, list(active_orders.keys())[:25])
        
        await interaction.response.edit_message(
            embed=embed,
            view=view
        )


class CancelFromSearchButton(discord.ui.Button):
    """Button to cancel work order from search view"""
    def __init__(self, cog: ArtisanEconomy, order_id: str):
        super().__init__(
            label="Cancel Work Order",
            style=discord.ButtonStyle.danger,
            emoji="❌"
        )
        self.cog = cog
        self.order_id = order_id
    
    async def callback(self, interaction: discord.Interaction):
        order = self.cog.work_orders.get(self.order_id)
        if not order:
            await interaction.response.send_message(
                "❌ This work order no longer exists.",
                ephemeral=True
            )
            return
        
        # Show confirmation
        view = CancelWorkOrderConfirmView(self.cog, self.order_id)
        
        materials = order.get('materials', {})
        mat_summary = []
        for mat_name in list(materials.keys())[:3]:
            mat_summary.append(f"• {mat_name}")
        
        if len(materials) > 3:
            mat_summary.append(f"• ...and {len(materials) - 3} more")
        
        await interaction.response.send_message(
            f"⚠️ **Are you sure you want to cancel this work order?**\n\n"
            f"**Order ID:** `{self.order_id}`\n"
            f"**Materials:**\n" + "\n".join(mat_summary) + "\n\n"
            f"This action cannot be undone.",
            view=view,
            ephemeral=True
        )


# =========================
# COMPLETE WORK ORDER CONFIRMATION VIEW
# =========================

class CompleteWorkOrderConfirmView(discord.ui.View):
    """Confirmation view for completing work orders"""
    def __init__(self, cog: ArtisanEconomy, order_id: str):
        super().__init__(timeout=60)
        self.cog = cog
        self.order_id = order_id
    
    @discord.ui.button(label="Yes, Complete Work Order", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm_complete(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Confirm completion"""
        await interaction.response.defer(ephemeral=True)
        
        order = self.cog.work_orders.get(self.order_id)
        if not order:
            await interaction.followup.send(
                "❌ Work order not found.",
                ephemeral=True
            )
            return
        
        # Mark as completed
        order['status'] = 'completed'
        order['completed_at'] = datetime.utcnow().isoformat()
        order['completed_by'] = interaction.user.id
        
        self.cog.save_data()
        
        # Log detailed completion to admin channel
        await self.cog.log_work_order_completion(self.order_id, interaction.user.id)
        
        # Delete the work order embed from the channel
        await self.cog.delete_work_order_embed(self.order_id)
        
        # Update control panel
        await self.cog.update_control_panel()
        
        await interaction.followup.send(
            f"✅ Work order `{self.order_id}` has been completed and archived!",
            ephemeral=True
        )
        
        # Delete the confirmation ephemeral message
        try:
            await interaction.message.delete()
        except:
            pass
    
    @discord.ui.button(label="No, Keep Active", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_action(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cancel the completion"""
        # Delete the ephemeral confirmation message
        try:
            await interaction.message.delete()
        except:
            await interaction.response.edit_message(
                content="✅ Work order remains active.",
                view=None
            )


# =========================
# CANCEL WORK ORDER CONFIRMATION VIEW
# =========================

class CancelWorkOrderConfirmView(discord.ui.View):
    """Confirmation view for cancelling work orders"""
    def __init__(self, cog: ArtisanEconomy, order_id: str):
        super().__init__(timeout=60)
        self.cog = cog
        self.order_id = order_id
    
    @discord.ui.button(label="Yes, Cancel Work Order", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Confirm cancellation"""
        await interaction.response.defer(ephemeral=True)
        
        order = self.cog.work_orders.get(self.order_id)
        if not order:
            await interaction.followup.send(
                "❌ Work order not found.",
                ephemeral=True
            )
            return
        
        # Mark as cancelled
        order['status'] = 'cancelled'
        order['cancelled_at'] = datetime.utcnow().isoformat()
        order['cancelled_by'] = interaction.user.id
        
        self.cog.save_data()
        
        # Log detailed cancellation to admin channel
        await self.cog.log_work_order_cancellation(self.order_id, interaction.user.id)
        
        # Delete the work order embed from the channel
        await self.cog.delete_work_order_embed(self.order_id)
        
        # Update control panel
        await self.cog.update_control_panel()
        
        await interaction.followup.send(
            f"✅ Work order `{self.order_id}` has been cancelled and removed from the channel.",
            ephemeral=True
        )
        
        # Delete the confirmation ephemeral message
        try:
            await interaction.message.delete()
        except:
            pass
    
    @discord.ui.button(label="No, Keep Work Order", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_action(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cancel the cancellation"""
        # Delete the ephemeral confirmation message
        try:
            await interaction.message.delete()
        except:
            await interaction.response.edit_message(
                content="✅ Work order cancellation aborted.",
                view=None
            )


# =========================
# SETUP FUNCTION
# =========================

async def setup(bot: commands.Bot):
    """Setup function for loading the cog"""
    await bot.add_cog(ArtisanEconomy(bot))
