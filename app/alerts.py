import os
import asyncio
from typing import Dict, Optional
import aiohttp


class AlertManager:
    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or os.getenv('DISCORD_WEBHOOK_URL')
        self._last_alerts = {}

    def check_and_notify(self, metrics: Dict):
        alerts = []
        if metrics.get('cpu_percent', 0) > 90:
            alerts.append(f"CPU usage high: {metrics['cpu_percent']:.1f}%")
        if metrics.get('ram_percent', 0) > 90:
            alerts.append(f"RAM usage high: {metrics['ram_percent']:.1f}%")
        if metrics.get('disk_percent', 0) > 80:
            alerts.append(f"Disk usage high: {metrics['disk_percent']:.1f}%")

        if alerts and self.webhook_url:
            # Debounce: avoid sending same alert repeatedly within short time
            key = ";".join(alerts)
            if self._last_alerts.get(key):
                return
            self._last_alerts[key] = True
            asyncio.create_task(self._send_discord("\n".join(alerts)))

    async def _send_discord(self, message: str):
        if not self.webhook_url:
            return
        payload = {"content": message}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=payload) as resp:
                    await resp.text()
        except Exception:
            pass
