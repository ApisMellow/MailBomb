import click

@click.group()
def cli():
    """MailBomb — prune massive Gmail mailboxes."""
    pass

if __name__ == "__main__":
    cli()
