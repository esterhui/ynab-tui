# BUGS

- A ynab pull actually changed from categorized to uncategorized even though they were pushed
- Split transactions show (Split) and not [Split 3], some show Split (Pending) (even though nothing is pending)
- pull should have a --dry-run to show you what it will do, meaning don't insert into DB, but show what will be inserted, what will be updated (and what changed for the update)
- the pull --since-days doesn't work with --ynab-only (always pulls a bunch of days)
- change --ynab/amazon-only flags to --ynab and --amazon (only isn't necessary)

- Dynamically scale other columns too (like pending changes window)
- Uncat doesn't update after cat and push (filtered view)
- Escape to exit from filter menu (if no filter needed)
- Escape to clear filters
