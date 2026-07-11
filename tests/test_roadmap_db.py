from roadmap.db import (
    clear_milestones,
    connect,
    create_goal,
    get_goal,
    get_milestone,
    insert_milestone,
    list_milestones,
    update_milestone_status,
)


def test_get_goal_returns_none_when_empty(tmp_path):
    conn = connect(tmp_path / "roadmap.db")
    try:
        assert get_goal(conn) is None
    finally:
        conn.close()


def test_create_and_get_goal(tmp_path):
    conn = connect(tmp_path / "roadmap.db")
    try:
        create_goal(conn, "Land a UK sponsorship offer", "2026-12-10")
        goal = get_goal(conn)
        assert goal["description"] == "Land a UK sponsorship offer"
        assert goal["target_date"] == "2026-12-10"
    finally:
        conn.close()


def test_get_goal_returns_most_recent(tmp_path):
    conn = connect(tmp_path / "roadmap.db")
    try:
        create_goal(conn, "old goal", "2026-11-01")
        create_goal(conn, "new goal", "2026-12-10")
        assert get_goal(conn)["description"] == "new goal"
    finally:
        conn.close()


def test_insert_and_list_milestones_in_sort_order(tmp_path):
    conn = connect(tmp_path / "roadmap.db")
    try:
        insert_milestone(conn, "2026-08", "second", 1)
        insert_milestone(conn, "2026-07", "first", 0)

        milestones = list_milestones(conn)
        assert [m["title"] for m in milestones] == ["first", "second"]
        assert all(m["status"] == "pending" for m in milestones)
    finally:
        conn.close()


def test_update_milestone_status(tmp_path):
    conn = connect(tmp_path / "roadmap.db")
    try:
        milestone_id = insert_milestone(conn, "2026-07", "DSA fundamentals", 0)
        update_milestone_status(conn, milestone_id, "done")

        milestone = get_milestone(conn, milestone_id)
        assert milestone["status"] == "done"
        assert milestone["updated_at"] is not None
    finally:
        conn.close()


def test_clear_milestones_removes_all(tmp_path):
    conn = connect(tmp_path / "roadmap.db")
    try:
        insert_milestone(conn, "2026-07", "first", 0)
        insert_milestone(conn, "2026-08", "second", 1)
        clear_milestones(conn)
        assert list_milestones(conn) == []
    finally:
        conn.close()
