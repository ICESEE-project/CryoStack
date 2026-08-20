import sqlite3

db = "var/cryostack_auth.db"

con = sqlite3.connect(db)
con.row_factory = sqlite3.Row

print("\n=== USERS ===")
for row in con.execute(
    """
    SELECT
        id,
        email,
        display_name,
        created_at
    FROM users
    ORDER BY created_at
    """
):
    print(dict(row))

print("\n=== IDENTITIES ===")
for row in con.execute(
    """
    SELECT
        user_id,
        provider,
        provider_subject,
        provider_username,
        provider_email
    FROM user_identities
    ORDER BY created_at
    """
):
    print(dict(row))

print("\n=== EXPERIMENT COUNTS BY USER ===")
for row in con.execute(
    """
    SELECT
        u.id,
        u.email,
        u.display_name,
        COUNT(e.id) AS experiments
    FROM users u
    LEFT JOIN experiments e
        ON e.user_id = u.id
    GROUP BY
        u.id,
        u.email,
        u.display_name
    ORDER BY experiments DESC
    """
):
    print(dict(row))

print("\n=== EXPERIMENTS ===")
for row in con.execute(
    """
    SELECT
        e.id,
        e.user_id,
        u.email,
        e.application,
        e.name,
        e.status,
        e.job_id
    FROM experiments e
    LEFT JOIN users u
        ON u.id = e.user_id
    ORDER BY e.created_at DESC
    """
):
    print(dict(row))

con.close()
