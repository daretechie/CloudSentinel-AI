"""
Slack notification service for Valdrix.
Sends alerts and daily digests to configured Slack channel.
"""
import logging
from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)


class SlackService:
    """Service for sending notifications to Slack."""
    
    # Color mapping for severity levels
    SEVERITY_COLORS = {
        "info": "#10b981",      # Green
        "warning": "#f59e0b",   # Amber  
        "critical": "#f43f5e",  # Red
    }
    
    def __init__(self, bot_token: str, channel_id: str):
        """Initialize with bot token and target channel."""
        self.client = WebClient(token=bot_token)
        self.channel_id = channel_id
        
    async def send_alert(
        self, 
        title: str, 
        message: str, 
        severity: str = "warning"
    ) -> bool:
        """
        Send an alert message to Slack.
        
        Args:
            title: Alert headline
            message: Detailed message
            severity: info | warning | critical
            
        Returns:
            True if sent successfully, False otherwise
        """
        color = self.SEVERITY_COLORS.get(severity, self.SEVERITY_COLORS["warning"])
        
        try:
            # WebClient is sync, so we use it directly (it's fast enough)
            self.client.chat_postMessage(
                channel=self.channel_id,
                attachments=[
                    {
                        "color": color,
                        "blocks": [
                            {
                                "type": "header",
                                "text": {"type": "plain_text", "text": f"🚨 {title}"}
                            },
                            {
                                "type": "section",
                                "text": {"type": "mrkdwn", "text": message}
                            },
                        ]
                    }
                ]
            )
            logger.info(f"Slack alert sent: {title}")
            return True
        except SlackApiError as e:
            logger.error(f"Slack API error: {e.response['error']}")
            return False
        except Exception as e:
            logger.error(f"Slack send failed: {e}")
            return False
            
    async def send_digest(self, stats: dict[str, Any]) -> bool:
        """
        Send daily cost digest to Slack.
        
        Args:
            stats: Dict with keys: total_cost, carbon_kg, zombie_count, period
        """
        try:
            self.client.chat_postMessage(
                channel=self.channel_id,
                blocks=[
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": "📊 Daily Cloud Cost Digest"}
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*💰 Total Cost*\n${stats.get('total_cost', 0):.2f}"},
                            {"type": "mrkdwn", "text": f"*🌱 Carbon*\n{stats.get('carbon_kg', 0):.2f} kg CO₂"},
                            {"type": "mrkdwn", "text": f"*👻 Zombies*\n{stats.get('zombie_count', 0)} resources"},
                            {"type": "mrkdwn", "text": f"*📅 Period*\n{stats.get('period', 'Last 24h')}"},
                        ]
                    },
                    {
                        "type": "context",
                        "elements": [
                            {"type": "mrkdwn", "text": "Powered by Valdrix"}
                        ]
                    }
                ]
            )
            logger.info("Slack daily digest sent")
            return True
        except SlackApiError as e:
            logger.error(f"Slack digest error: {e.response['error']}")
            return False
    
    async def notify_zombies(self, zombies: dict[str, Any], estimated_savings: float = 0.0) -> bool:
        """
        Send zombie detection alert.
        
        Args:
            zombies: Dict of zombie categories to lists of resources
            estimated_savings: Estimated monthly savings in dollars
        """
        zombie_count = sum(len(items) for items in zombies.values() if isinstance(items, list))
        if zombie_count == 0:
            return True  # No zombies, nothing to report
        
        summary_lines = []
        for cat, items in zombies.items():
            if isinstance(items, list) and len(items) > 0:
                label = cat.replace("_", " ").title()
                summary_lines.append(f"• {label}: {len(items)}")
        
        message = (
            f"Found *{zombie_count} zombie resources*.\n" +
            "\n".join(summary_lines) +
            f"\n💰 Estimated Savings: *${estimated_savings:.2f}/mo*"
        )
        
        return await self.send_alert(
            title="Zombie Resources Detected!",
            message=message,
            severity="warning"
        )
    
    async def notify_budget_alert(
        self, 
        current_spend: float, 
        budget_limit: float, 
        percent_used: float
    ) -> bool:
        """
        Send budget threshold alert.
        
        Args:
            current_spend: Current spend amount
            budget_limit: Budget limit
            percent_used: Percentage of budget used (0-100)
        """
        severity = "critical" if percent_used >= 100 else "warning"
        
        message = (
            f"*Current Spend:* ${current_spend:.2f}\n"
            f"*Budget Limit:* ${budget_limit:.2f}\n"
            f"*Usage:* {percent_used:.1f}%"
        )
        
        return await self.send_alert(
            title="Budget Alert Threshold Reached",
            message=message,
            severity=severity
        )


def get_slack_service():
    """
    Factory function to get a configured SlackService instance.
    Returns None if Slack is not configured.
    """
    from app.core.config import get_settings
    settings = get_settings()
    
    if settings.SLACK_BOT_TOKEN and settings.SLACK_CHANNEL_ID:
        return SlackService(settings.SLACK_BOT_TOKEN, settings.SLACK_CHANNEL_ID)
    return None