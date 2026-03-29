import webbrowser
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

from mailbomb.auth import get_credentials_path, get_token_path, get_gmail_service
from mailbomb.db import init_db
from mailbomb.scanner import scan_messages
from mailbomb.analyzer import top_senders_by_count, top_senders_by_size, mailing_lists, breakdown_by_year, total_size
from mailbomb.executor import delete_messages, resolve_message_ids

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


@cli.command()
@click.option("--before", default=None, help="Filter messages before this date")
@click.option("--after", default=None, help="Filter messages after this date")
@click.option("--top", default=20, help="Number of top entries to show")
def analyze(before, after, top):
    """Analyze scanned message metadata for patterns."""
    from rich.table import Table
    from mailbomb.db import get_connection

    conn = get_connection()

    # Top senders by count
    console.print("\n[bold]Top Senders by Message Count:[/bold]")
    table = Table()
    table.add_column("Sender", style="cyan")
    table.add_column("Count", justify="right")
    for row in top_senders_by_count(conn, limit=top):
        table.add_row(row["sender_email"], f"{row['count']:,}")
    console.print(table)

    # Top senders by size
    console.print("\n[bold]Top Senders by Total Size:[/bold]")
    table = Table()
    table.add_column("Sender", style="cyan")
    table.add_column("Size", justify="right")
    table.add_column("Count", justify="right")
    for row in top_senders_by_size(conn, limit=top):
        size_mb = row["total_size"] / (1024 * 1024)
        table.add_row(row["sender_email"], f"{size_mb:.1f} MB", f"{row['count']:,}")
    console.print(table)

    # Mailing lists
    lists = mailing_lists(conn)
    if lists:
        console.print("\n[bold]Mailing Lists:[/bold]")
        table = Table()
        table.add_column("List-Id", style="cyan")
        table.add_column("Count", justify="right")
        table.add_column("Size", justify="right")
        for row in lists:
            size_mb = row["total_size"] / (1024 * 1024)
            table.add_row(row["list_id"], f"{row['count']:,}", f"{size_mb:.1f} MB")
        console.print(table)

    # Year breakdown
    console.print("\n[bold]Messages by Year:[/bold]")
    table = Table()
    table.add_column("Year", style="cyan")
    table.add_column("Count", justify="right")
    table.add_column("Size", justify="right")
    for row in breakdown_by_year(conn):
        size_mb = (row["total_size"] or 0) / (1024 * 1024)
        table.add_row(row["year"], f"{row['count']:,}", f"{size_mb:.1f} MB")
    console.print(table)

    # Total
    total = total_size(conn)
    console.print(f"\n[bold]Total indexed:[/bold] {total / (1024*1024):.1f} MB")
    conn.close()


@cli.command()
@click.option("--sender", default=None, help="Delete all messages from this sender email")
@click.option("--list-id", default=None, help="Delete all messages with this List-Id")
@click.option("--before", default=None, help="Delete messages before this date")
@click.option("--after", default=None, help="Delete messages after this date")
@click.option("--min-size", default=None, help="Delete messages larger than this (e.g., 5MB)")
@click.option("--dry-run", is_flag=True, help="Show what would be deleted without deleting")
def delete(sender, list_id, before, after, min_size, dry_run):
    """Delete messages matching the given filters."""
    from rich.table import Table
    from mailbomb.db import get_connection

    if not any([sender, list_id, before, min_size]):
        console.print("[red]Specify at least one filter (--sender, --list-id, --before, --min-size)[/red]")
        raise SystemExit(1)

    # Parse min_size like "5MB" to bytes
    size_bytes = None
    if min_size:
        min_size = min_size.upper()
        if min_size.endswith("MB"):
            size_bytes = int(float(min_size[:-2]) * 1024 * 1024)
        elif min_size.endswith("KB"):
            size_bytes = int(float(min_size[:-2]) * 1024)
        elif min_size.endswith("GB"):
            size_bytes = int(float(min_size[:-2]) * 1024 * 1024 * 1024)
        else:
            size_bytes = int(min_size)

    conn = get_connection()
    ids = resolve_message_ids(
        conn,
        sender_email=sender,
        list_id=list_id,
        before=before,
        after=after,
        min_size=size_bytes,
    )

    if not ids:
        console.print("[yellow]No matching messages found.[/yellow]")
        conn.close()
        return

    # Show summary
    total_size_bytes = conn.execute(
        f"SELECT COALESCE(SUM(size_bytes), 0) FROM messages WHERE gmail_id IN ({','.join('?' for _ in ids)})",
        ids,
    ).fetchone()[0]

    console.print(f"\n[bold]Messages to delete:[/bold] {len(ids):,}")
    console.print(f"[bold]Space to reclaim:[/bold] {total_size_bytes / (1024*1024):.1f} MB")

    if dry_run:
        console.print("\n[yellow]Dry run — no messages deleted.[/yellow]")
        conn.close()
        return

    if not click.confirm(f"\nPermanently delete {len(ids):,} messages?"):
        console.print("Cancelled.")
        conn.close()
        return

    conn.close()
    deleted = delete_messages(ids)
    console.print(f"\n[green]✓ Deleted {deleted:,} messages[/green]")


@cli.command()
def stats():
    """Show scanning and deletion progress."""
    from mailbomb.db import get_connection, count_messages

    conn = get_connection()

    total = count_messages(conn, include_deleted=True)
    active = count_messages(conn, include_deleted=False)
    deleted = total - active

    active_size = conn.execute(
        "SELECT COALESCE(SUM(size_bytes), 0) FROM messages WHERE deleted = 0"
    ).fetchone()[0]
    deleted_size = conn.execute(
        "SELECT COALESCE(SUM(size_bytes), 0) FROM messages WHERE deleted = 1"
    ).fetchone()[0]

    console.print(f"\n[bold]MailBomb Stats[/bold]")
    console.print(f"  Messages scanned:  {total:,}")
    console.print(f"  Active (kept):     {active:,} ({active_size / (1024*1024):.1f} MB)")
    console.print(f"  Deleted:           {deleted:,} ({deleted_size / (1024*1024):.1f} MB reclaimed)")
    conn.close()


if __name__ == "__main__":
    cli()
