"""Admin-only lightweight analysis; all measures share one filtered population."""

import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select, func
from sqlalchemy.orm import Session, aliased
from .db import database
from .models import Ticket, Team, User

TZ = ZoneInfo("Asia/Shanghai")
LABELS = {
    "open": "待受理",
    "in_progress": "处理中",
    "resolved": "待确认",
    "closed": "已关闭",
    "cancelled": "已取消",
    "erp": "ERP 问题",
    "operations": "运维工单",
    "low": "低",
    "normal": "普通",
    "high": "高",
    "urgent": "紧急",
}


def selection(
    start: date | None = None,
    end: date | None = None,
    status: (
        Literal["open", "in_progress", "resolved", "closed", "cancelled"] | None
    ) = None,
    category: Literal["erp", "operations"] | None = None,
    priority: Literal["low", "normal", "high", "urgent"] | None = None,
    team_id: int | None = Query(None, ge=0),
    assignee_id: int | None = Query(None, ge=0),
):
    end = end or datetime.now(TZ).date()
    start = start or end - timedelta(days=29)
    if start > end or (end - start).days > 365:
        raise HTTPException(422, "Choose a date range of at most 366 days")
    lo = datetime.combine(start, time.min, TZ).astimezone(timezone.utc)
    hi = datetime.combine(end + timedelta(days=1), time.min, TZ).astimezone(
        timezone.utc
    )
    clauses = [Ticket.created_at >= lo, Ticket.created_at < hi]
    for field, value in [
        (Ticket.status, status),
        (Ticket.category, category),
        (Ticket.priority, priority),
    ]:
        if value is not None:
            clauses.append(field == value)
    for field, value in [(Ticket.team_id, team_id), (Ticket.assignee_id, assignee_id)]:
        if value is not None:
            clauses.append(field.is_(None) if value == 0 else field == value)
    return start, end, clauses


def safe_cell(value):
    value = "" if value is None else str(value)
    # Excel may execute formulas after leading whitespace/control characters.
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(
        ("\t", "\r", "\n")
    ):
        return "'" + value
    return value


def make_router(current):
    router = APIRouter(prefix="/api/admin/analytics", tags=["analytics"])

    def admin(user=Depends(current)):
        if user.role != "admin":
            raise HTTPException(403, "Admin role required")
        return user

    @router.get("")
    def analyze(
        filters=Depends(selection), db: Session = Depends(database), user=Depends(admin)
    ):
        start, end, clauses = filters

        def grouped(field, names=None):
            values = db.execute(
                select(field, func.count())
                .select_from(Ticket)
                .where(*clauses)
                .group_by(field)
            ).all()
            return [
                {
                    "key": key if key is not None else 0,
                    "label": (names or LABELS).get(
                        key, "未分配" if key is None else str(key)
                    ),
                    "count": count,
                }
                for key, count in sorted(values, key=lambda v: (-v[1], str(v[0])))
            ]

        statuses = grouped(Ticket.status)
        counts = {row["key"]: row["count"] for row in statuses}
        total = sum(counts.values())
        active = sum(counts.get(v, 0) for v in ["open", "in_progress", "resolved"])
        unassigned = (
            db.scalar(
                select(func.count())
                .select_from(Ticket)
                .where(
                    *clauses,
                    Ticket.assignee_id.is_(None),
                    Ticket.status.in_(["open", "in_progress", "resolved"]),
                )
            )
            or 0
        )
        urgent = (
            db.scalar(
                select(func.count())
                .select_from(Ticket)
                .where(
                    *clauses,
                    Ticket.priority == "urgent",
                    Ticket.status.in_(["open", "in_progress", "resolved"]),
                )
            )
            or 0
        )
        day = (
            func.date(func.timezone("Asia/Shanghai", Ticket.created_at))
            if db.bind.dialect.name == "postgresql"
            else func.date(Ticket.created_at, "+8 hours")
        )
        daily = {
            str(k): v
            for k, v in db.execute(
                select(day, func.count()).where(*clauses).group_by(day)
            ).all()
        }
        trend = [
            {
                "date": str(start + timedelta(days=i)),
                "count": daily.get(str(start + timedelta(days=i)), 0),
            }
            for i in range((end - start).days + 1)
        ]
        result = {
            "start": str(start),
            "end": str(end),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "timezone": "Asia/Shanghai",
            "summary": {
                "total": total,
                "active": active,
                "closed": counts.get("closed", 0),
                "closed_rate": (
                    round(counts.get("closed", 0) / total * 100, 1) if total else 0
                ),
                "unassigned_active": unassigned,
                "urgent_active": urgent,
            },
            "by_status": statuses,
            "by_priority": grouped(Ticket.priority),
            "by_category": grouped(Ticket.category),
            "by_team": grouped(
                Ticket.team_id, dict(db.execute(select(Team.id, Team.name)).all())
            ),
            "by_assignee": grouped(
                Ticket.assignee_id,
                {
                    u.id: u.display_name or u.username
                    for u in db.scalars(select(User)).all()
                },
            ),
            "trend": trend,
        }
        return result

    @router.get("/export")
    def export(
        kind: Literal["details", "summary"] = "details",
        filters=Depends(selection),
        db: Session = Depends(database),
        user=Depends(admin),
    ):
        start, end, clauses = filters
        output = io.StringIO(newline="")
        writer = csv.writer(output)

        def write(values):
            writer.writerow([safe_cell(v) for v in values])

        if kind == "summary":
            result = analyze(filters, db, user)
            write(["统计范围（创建日期，北京时间）", str(start), str(end)])
            write(["指标", "值"])
            names = {
                "total": "工单总数",
                "active": "当前未关闭",
                "closed": "当前已关闭",
                "closed_rate": "当前关闭率（%）",
                "unassigned_active": "未分派且未关闭",
                "urgent_active": "紧急且未关闭",
            }
            for key, value in result["summary"].items():
                write([names[key], value])
            write([])
            write(["维度", "项目", "工单数"])
            for key, label in [
                ("by_status", "当前状态"),
                ("by_priority", "优先级"),
                ("by_category", "类型"),
                ("by_team", "处理组"),
                ("by_assignee", "处理人"),
            ]:
                for row in result[key]:
                    write([label, row["label"], row["count"]])
            for row in result["trend"]:
                write(["创建日期", row["date"], row["count"]])
        else:
            creator = aliased(User)
            assignee = aliased(User)
            rows = db.execute(
                select(
                    Ticket,
                    Team.name,
                    creator.display_name,
                    creator.username,
                    assignee.display_name,
                    assignee.username,
                )
                .outerjoin(Team, Ticket.team_id == Team.id)
                .join(creator, Ticket.creator_id == creator.id)
                .outerjoin(assignee, Ticket.assignee_id == assignee.id)
                .where(*clauses)
                .order_by(Ticket.created_at.desc(), Ticket.id.desc())
                .limit(10001)
            ).all()
            if len(rows) > 10000:
                raise HTTPException(
                    413, "Report exceeds 10000 rows; narrow the filters"
                )
            write(
                [
                    "工单编号",
                    "标题",
                    "类型",
                    "优先级",
                    "当前状态",
                    "处理组",
                    "申请人",
                    "处理人",
                    "创建时间（北京时间）",
                    "更新时间（北京时间）",
                ]
            )

            def local(value):
                return (
                    (
                        value.replace(tzinfo=timezone.utc)
                        if value.tzinfo is None
                        else value
                    )
                    .astimezone(TZ)
                    .strftime("%Y-%m-%d %H:%M:%S")
                )

            for t, team, cn, cu, an, au in rows:
                write(
                    [
                        t.id,
                        t.title,
                        LABELS[t.category],
                        LABELS[t.priority],
                        LABELS[t.status],
                        team or "未分配",
                        cn or cu,
                        an or au or "未分配",
                        local(t.created_at),
                        local(t.updated_at),
                    ]
                )
        return Response(
            content=("\ufeff" + output.getvalue()).encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="ticketflow-{kind}-{start}-{end}.csv"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return router
