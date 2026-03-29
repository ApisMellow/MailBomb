import webbrowser
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

from mailbomb.auth import get_credentials_path, get_token_path, get_gmail_service
from mailbomb.db import init_db
from mailbomb.scanner import scan_messages

console = Console()


@click.group()
def cli():
    """MailBomb — prune massive Gmail mailboxes."""
    pass


@cli.command()
def setup():
    """Set up Gmail API credentials and authenticate."""
    console.print(Panel("MailBomb Setup", style="bold blue"))

    credentials_path = get_credentials_path()
    token_path = get_token_path()

    if not credentials_path.exists():
        console.print("\n[bold]Step 1:[/bold] Create Google Cloud OAuth credentials\n")
        console.print("1. Go to [link]https://console.cloud.google.com/apis/credentials[/link]")
        console.print("2. Create a project (or select existing)")
        console.print("3. Enable the Gmail API at [link]https://console.cloud.google.com/apis/library/gmail.googleapis.com[/link]")
        console.print("4. Go to Credentials → Create Credentials → OAuth client ID")
        console.print("5. Application type: Desktop app")
        console.print("6. Download the JSON file")
        console.print(f"7. Save it as: [bold]{credentials_path}[/bold]\n")

        if click.confirm("Open Google Cloud Console in your browser?"):
            webbrowser.open("https://console.cloud.google.com/apis/credentials")

        click.pause("Press any key once you've saved credentials.json...")

        if not credentials_path.exists():
            console.print(f"\n[red]credentials.json not found at {credentials_path}[/red]")
            console.print("Please save the file and run 'mailbomb setup' again.")
            raise SystemExit(1)

    console.print("\n[bold]Authenticating with Gmail...[/bold]")
    service = get_gmail_service(token_path=token_path, credentials_path=credentials_path)

    profile = service.users().getProfile(userId="me").execute()
    email = profile.get("emailAddress", "unknown")
    total = profile.get("messagesTotal", 0)

    console.print(f"\n[green]✓ Authenticated as {email}[/green]")
    console.print(f"  Total messages: {total:,}")

    init_db()
    console.print("[green]✓ Database initialized[/green]")
    console.print("\n[bold]Setup complete![/bold] Run [bold]mailbomb scan --help[/bold] to get started.")


@cli.command()
@click.option("--before", required=True, help="Scan messages before this date (YYYY-MM-DD)")
@click.option("--after", default=None, help="Scan messages after this date (YYYY-MM-DD)")
@click.option("--batch-size", default=100, help="Messages per API page (max 500)")
def scan(before, after, batch_size):
    """Scan Gmail and index message metadata locally."""
    query_parts = []
    if before:
        query_parts.append(f"before:{before.replace('-', '/')}")
    if after:
        query_parts.append(f"after:{after.replace('-', '/')}")

    query = " ".join(query_parts)
    console.print(f"[bold]Scanning:[/bold] {query}")

    result = scan_messages(query=query, batch_size=batch_size)

    console.print(f"\n[green]✓ Done![/green] Fetched {result['fetched']:,} new, skipped {result['skipped']:,} existing")


if __name__ == "__main__":
    cli()
