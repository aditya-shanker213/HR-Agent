"""
Audit log and tool log repository.

Purpose:
- MongoDB operations for audit_logs and tool_logs collections
- Append-only audit log pattern
- Tool logs support insert + completion update only
- Query/filter operations for audit trails
- Statistics for dashboard

Pattern:
Route → Service → Repository → MongoDB

Important:
- Audit logs are append-only. Do not update/delete audit logs.
- Tool logs can be updated only to mark completion/failure/timeout.
- Repository does not decide business rules.
- Service validates payloads using audit_log_model.py before insert.
"""

from __future__ import annotations

from datetime import datetime as DateTime
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING


class BaseLogRepository:
    """
    Shared helpers for audit/tool log repositories.
    """

    VALID_SORT_ORDERS = {"asc", "desc"}

    def _to_object_id(self, value: str) -> Optional[ObjectId]:
        """
        Safely convert string to ObjectId.
        """
        try:
            return ObjectId(str(value))
        except (InvalidId, TypeError):
            return None

    def _convert_id(self, document: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Convert MongoDB _id to string id.
        """
        if document and "_id" in document:
            document["_id"] = str(document["_id"])
            document["id"] = document["_id"]

        return document

    def _convert_many(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Convert MongoDB _id for many documents.
        """
        return [self._convert_id(document) for document in documents if document]

    def _clean_pagination(self, skip: int = 0, limit: int = 100) -> Tuple[int, int]:
        """
        Clamp pagination values.
        """
        skip = max(0, int(skip or 0))
        limit = max(1, min(int(limit or 100), 500))
        return skip, limit

    def _normalize_company_id(self, company_id: Optional[str] = "default") -> str:
        """
        Normalize company_id.
        """
        if not company_id:
            return "default"

        company_id = str(company_id).strip().lower()

        if not company_id:
            return "default"

        if not company_id.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                "company_id can contain only letters, numbers, hyphen, and underscore"
            )

        return company_id

    def _normalize_text(self, value: Optional[str]) -> Optional[str]:
        """
        Normalize optional text.
        """
        if value is None:
            return None

        value = str(value).strip()
        return value or None

    def _date_range_query(
        self,
        field_name: str,
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
    ) -> Dict[str, Any]:
        """
        Build date range query.
        """
        query: Dict[str, Any] = {}

        if start_date:
            query["$gte"] = start_date

        if end_date:
            query["$lte"] = end_date

        return {field_name: query} if query else {}

    def _sort_direction(self, sort_order: str = "desc") -> int:
        """
        Convert sort order string to pymongo direction.
        """
        return ASCENDING if str(sort_order).lower() == "asc" else DESCENDING


class AuditLogRepository(BaseLogRepository):
    """
    Repository for audit_logs collection.

    Audit logs are append-only:
    - create allowed
    - read/query allowed
    - update/delete intentionally not implemented
    """

    VALID_SORT_FIELDS = {
        "schema_version",
        "created_at",
        "category",
        "action",
        "status",
        "sensitivity",
        "company_id",
        "actor.actor_id",
        "target.target_id",
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.audit_logs

    # -------------------------
    # Create
    # -------------------------

    async def create(self, audit_log_data: Dict[str, Any]) -> str:
        """
        Create new audit log entry.

        Returns:
            inserted document id
        """
        result = await self.collection.insert_one(audit_log_data)
        return str(result.inserted_id)

    async def create_many(self, logs: List[Dict[str, Any]]) -> List[str]:
        """
        Insert multiple audit logs.

        Mostly useful for sync jobs/scripts.
        """
        if not logs:
            return []

        result = await self.collection.insert_many(logs, ordered=False)
        return [str(item) for item in result.inserted_ids]

    # -------------------------
    # Read single
    # -------------------------

    async def find_by_id(
        self,
        log_id: str,
        company_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Find audit log by MongoDB _id.
        """
        object_id = self._to_object_id(log_id)

        if object_id is None:
            return None

        query: Dict[str, Any] = {"_id": object_id}

        if company_id is not None:
            query["company_id"] = self._normalize_company_id(company_id)

        document = await self.collection.find_one(query)
        return self._convert_id(document)

    # -------------------------
    # Advanced query
    # -------------------------

    async def list_logs(
        self,
        company_id: str = "default",
        actor_id: Optional[str] = None,
        actor_type: Optional[str] = None,
        actor_role: Optional[str] = None,
        category: Optional[str] = None,
        action: Optional[str] = None,
        status: Optional[str] = None,
        sensitivity: Optional[str] = None,
        is_sensitive: Optional[bool] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        employee_id: Optional[str] = None,
        source: Optional[str] = None,
        external_hrms_id: Optional[str] = None,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> List[Dict[str, Any]]:
        """
        List audit logs with filters.
        """
        skip, limit = self._clean_pagination(skip, limit)

        if sort_by not in self.VALID_SORT_FIELDS:
            sort_by = "created_at"

        query = self._build_list_query(
            company_id=company_id,
            actor_id=actor_id,
            actor_type=actor_type,
            actor_role=actor_role,
            category=category,
            action=action,
            status=status,
            sensitivity=sensitivity,
            is_sensitive=is_sensitive,
            target_type=target_type,
            target_id=target_id,
            employee_id=employee_id,
            source=source,
            external_hrms_id=external_hrms_id,
            request_id=request_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            start_date=start_date,
            end_date=end_date,
            search=search,
        )

        cursor = (
            self.collection.find(query)
            .sort(sort_by, self._sort_direction(sort_order))
            .skip(skip)
            .limit(limit)
        )

        documents = await cursor.to_list(length=limit)
        return self._convert_many(documents)

    async def count_logs(
        self,
        company_id: str = "default",
        actor_id: Optional[str] = None,
        actor_type: Optional[str] = None,
        actor_role: Optional[str] = None,
        category: Optional[str] = None,
        action: Optional[str] = None,
        status: Optional[str] = None,
        sensitivity: Optional[str] = None,
        is_sensitive: Optional[bool] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        employee_id: Optional[str] = None,
        source: Optional[str] = None,
        external_hrms_id: Optional[str] = None,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
        search: Optional[str] = None,
    ) -> int:
        """
        Count audit logs with filters.
        """
        query = self._build_list_query(
            company_id=company_id,
            actor_id=actor_id,
            actor_type=actor_type,
            actor_role=actor_role,
            category=category,
            action=action,
            status=status,
            sensitivity=sensitivity,
            is_sensitive=is_sensitive,
            target_type=target_type,
            target_id=target_id,
            employee_id=employee_id,
            source=source,
            external_hrms_id=external_hrms_id,
            request_id=request_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            start_date=start_date,
            end_date=end_date,
            search=search,
        )

        return await self.collection.count_documents(query)

    def _build_list_query(
        self,
        company_id: str = "default",
        actor_id: Optional[str] = None,
        actor_type: Optional[str] = None,
        actor_role: Optional[str] = None,
        category: Optional[str] = None,
        action: Optional[str] = None,
        status: Optional[str] = None,
        sensitivity: Optional[str] = None,
        is_sensitive: Optional[bool] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        employee_id: Optional[str] = None,
        source: Optional[str] = None,
        external_hrms_id: Optional[str] = None,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build common audit list query.
        """
        query: Dict[str, Any] = {
            "company_id": self._normalize_company_id(company_id),
        }

        filters = {
            "actor.actor_id": actor_id,
            "actor.actor_type": actor_type,
            "actor.actor_role": actor_role,
            "category": category,
            "action": action,
            "status": status,
            "sensitivity": sensitivity,
            "target.target_type": target_type,
            "target.target_id": target_id,
            "target.employee_id": employee_id,
            "source": source,
            "external_hrms_id": external_hrms_id,
            "request.request_id": request_id,
            "request.correlation_id": correlation_id,
            "request.trace_id": trace_id,
        }

        for key, value in filters.items():
            value = self._normalize_text(value)
            if value is not None:
                query[key] = value

        if is_sensitive is not None:
            query["is_sensitive"] = is_sensitive

        query.update(
            self._date_range_query(
                field_name="created_at",
                start_date=start_date,
                end_date=end_date,
            )
        )

        search = self._normalize_text(search)
        if search:
            query["$or"] = [
                {"message": {"$regex": search, "$options": "i"}},
                {"reason": {"$regex": search, "$options": "i"}},
                {"action": {"$regex": search, "$options": "i"}},
                {"target.target_display": {"$regex": search, "$options": "i"}},
                {"actor.actor_name": {"$regex": search, "$options": "i"}},
                {"actor.actor_email": {"$regex": search, "$options": "i"}},
                {"error_message": {"$regex": search, "$options": "i"}},
            ]

        return query

    # -------------------------
    # Compatibility query helpers
    # -------------------------

    async def find_by_actor(
        self,
        actor_id: str,
        company_id: str = "default",
        category: Optional[str] = None,
        action: Optional[str] = None,
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
        limit: int = 100,
        skip: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Find audit logs by actor.
        """
        return await self.list_logs(
            company_id=company_id,
            actor_id=actor_id,
            category=category,
            action=action,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            skip=skip,
        )

    async def find_by_target(
        self,
        target_type: str,
        company_id: str = "default",
        target_id: Optional[str] = None,
        employee_id: Optional[str] = None,
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
        limit: int = 100,
        skip: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Find audit logs by target entity.
        """
        return await self.list_logs(
            company_id=company_id,
            target_type=target_type,
            target_id=target_id,
            employee_id=employee_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            skip=skip,
        )

    async def find_by_category(
        self,
        category: str,
        company_id: str = "default",
        action: Optional[str] = None,
        status: Optional[str] = None,
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
        limit: int = 100,
        skip: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Find audit logs by category.
        """
        return await self.list_logs(
            company_id=company_id,
            category=category,
            action=action,
            status=status,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            skip=skip,
        )

    async def find_sensitive_logs(
        self,
        company_id: str = "default",
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
        category: Optional[str] = None,
        limit: int = 100,
        skip: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Find logs marked as sensitive.
        """
        return await self.list_logs(
            company_id=company_id,
            category=category,
            is_sensitive=True,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            skip=skip,
        )

    async def find_by_company(
        self,
        company_id: str,
        category: Optional[str] = None,
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
        limit: int = 100,
        skip: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Find audit logs by company.
        """
        return await self.list_logs(
            company_id=company_id,
            category=category,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            skip=skip,
        )

    async def count_by_category(
        self,
        category: str,
        company_id: str = "default",
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
    ) -> int:
        """
        Count audit logs by category.
        """
        return await self.count_logs(
            company_id=company_id,
            category=category,
            start_date=start_date,
            end_date=end_date,
        )

    # -------------------------
    # Statistics
    # -------------------------

    async def get_statistics(
        self,
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
        company_id: str = "default",
    ) -> Dict[str, Any]:
        """
        Get audit log statistics.
        """
        match_stage: Dict[str, Any] = {
            "company_id": self._normalize_company_id(company_id),
        }

        if start_date or end_date:
            match_stage.update(
                self._date_range_query(
                    field_name="created_at",
                    start_date=start_date,
                    end_date=end_date,
                )
            )

        pipeline = [
            {"$match": match_stage},
            {
                "$facet": {
                    "total_count": [{"$count": "count"}],
                    "by_category": [
                        {"$group": {"_id": "$category", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}},
                    ],
                    "by_action": [
                        {"$group": {"_id": "$action", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}},
                        {"$limit": 20},
                    ],
                    "by_status": [
                        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}},
                    ],
                    "by_actor_type": [
                        {"$group": {"_id": "$actor.actor_type", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}},
                    ],
                    "sensitive_count": [
                        {"$match": {"is_sensitive": True}},
                        {"$count": "count"},
                    ],
                    "critical_count": [
                        {"$match": {"sensitivity": "critical"}},
                        {"$count": "count"},
                    ],
                }
            },
        ]

        result = await self.collection.aggregate(pipeline).to_list(length=1)

        if not result:
            return self._empty_statistics(company_id)

        data = result[0]

        by_status = {
            item["_id"]: item["count"]
            for item in data.get("by_status", [])
            if item.get("_id") is not None
        }

        return {
            "company_id": self._normalize_company_id(company_id),
            "total_logs": data["total_count"][0]["count"] if data["total_count"] else 0,
            "success_logs": by_status.get("success", 0),
            "failed_logs": by_status.get("failed", 0),
            "denied_logs": by_status.get("denied", 0),
            "blocked_logs": by_status.get("blocked", 0),
            "sensitive_logs": (
                data["sensitive_count"][0]["count"]
                if data["sensitive_count"]
                else 0
            ),
            "critical_logs": (
                data["critical_count"][0]["count"]
                if data["critical_count"]
                else 0
            ),
            "logs_by_category": {
                item["_id"]: item["count"]
                for item in data.get("by_category", [])
                if item.get("_id") is not None
            },
            "logs_by_action": {
                item["_id"]: item["count"]
                for item in data.get("by_action", [])
                if item.get("_id") is not None
            },
            "logs_by_actor_type": {
                item["_id"]: item["count"]
                for item in data.get("by_actor_type", [])
                if item.get("_id") is not None
            },
            "logs_by_status": by_status,
        }

    def _empty_statistics(self, company_id: str = "default") -> Dict[str, Any]:
        """
        Empty audit statistics.
        """
        return {
            "company_id": self._normalize_company_id(company_id),
            "total_logs": 0,
            "success_logs": 0,
            "failed_logs": 0,
            "denied_logs": 0,
            "blocked_logs": 0,
            "sensitive_logs": 0,
            "critical_logs": 0,
            "logs_by_category": {},
            "logs_by_action": {},
            "logs_by_actor_type": {},
            "logs_by_status": {},
        }


class ToolLogRepository(BaseLogRepository):
    """
    Repository for tool_logs collection.

    Tool logs are mostly append-only:
    - create allowed
    - completion update allowed
    - read/query allowed
    - delete intentionally not implemented
    """

    VALID_SORT_FIELDS = {
        "schema_version",
        "started_at",
        "completed_at",
        "latency_ms",
        "tool_name",
        "status",
        "company_id",
        "actor.actor_id",
    }

    FINAL_STATUSES = {"success", "failed", "blocked", "timeout"}

    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.tool_logs

    # -------------------------
    # Create/update
    # -------------------------

    async def create(self, tool_log_data: Dict[str, Any]) -> str:
        """
        Create new tool log entry.
        """
        result = await self.collection.insert_one(tool_log_data)
        return str(result.inserted_id)

    async def update_completion(
        self,
        log_id: str,
        status: str,
        completed_at: DateTime,
        latency_ms: int,
        output_summary: Optional[str] = None,
        output_category: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        blocked_reason: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Update tool log with completion details.

        This is the only allowed update operation for tool logs.
        It refuses to update already-final tool logs.
        """
        object_id = self._to_object_id(log_id)

        if object_id is None:
            return False

        status = str(status).strip().lower()

        if status not in self.FINAL_STATUSES:
            raise ValueError("status must be one of: success, failed, blocked, timeout")

        update_data: Dict[str, Any] = {
            "status": status,
            "completed_at": completed_at,
            "latency_ms": max(0, int(latency_ms or 0)),
        }

        output_summary = self._normalize_text(output_summary)
        output_category = self._normalize_text(output_category)
        error_code = self._normalize_text(error_code)
        error_message = self._normalize_text(error_message)
        blocked_reason = self._normalize_text(blocked_reason)

        if output_summary:
            update_data["output_summary"] = output_summary

        if output_category:
            update_data["output_category"] = output_category

        if error_code:
            update_data["error_code"] = error_code

        if error_message:
            update_data["error_message"] = error_message

        if blocked_reason:
            update_data["blocked_reason"] = blocked_reason

        if extra_metadata:
            for key, value in extra_metadata.items():
                safe_key = str(key).strip()

                if not safe_key or "." in safe_key or safe_key.startswith("$"):
                    raise ValueError(
                        "extra_metadata keys cannot be empty, contain '.', or start with '$'"
                    )

                update_data[f"extra_metadata.{safe_key}"] = value

        result = await self.collection.update_one(
            {
                "_id": object_id,
                "status": {"$nin": list(self.FINAL_STATUSES)},
            },
            {"$set": update_data},
        )

        return result.modified_count > 0

    # -------------------------
    # Read single
    # -------------------------

    async def find_by_id(
        self,
        log_id: str,
        company_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Find tool log by MongoDB _id.
        """
        object_id = self._to_object_id(log_id)

        if object_id is None:
            return None

        query: Dict[str, Any] = {"_id": object_id}

        if company_id is not None:
            query["company_id"] = self._normalize_company_id(company_id)

        document = await self.collection.find_one(query)
        return self._convert_id(document)

    # -------------------------
    # Advanced query
    # -------------------------

    async def list_tool_logs(
        self,
        company_id: str = "default",
        tool_name: Optional[str] = None,
        status: Optional[str] = None,
        actor_id: Optional[str] = None,
        actor_type: Optional[str] = None,
        session_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        input_category: Optional[str] = None,
        output_category: Optional[str] = None,
        is_sensitive: Optional[bool] = None,
        required_confirmation: Optional[bool] = None,
        confirmed_by_user: Optional[bool] = None,
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
        sort_by: str = "started_at",
        sort_order: str = "desc",
    ) -> List[Dict[str, Any]]:
        """
        List tool logs with filters.
        """
        skip, limit = self._clean_pagination(skip, limit)

        if sort_by not in self.VALID_SORT_FIELDS:
            sort_by = "started_at"

        query = self._build_tool_query(
            company_id=company_id,
            tool_name=tool_name,
            status=status,
            actor_id=actor_id,
            actor_type=actor_type,
            session_id=session_id,
            conversation_id=conversation_id,
            request_id=request_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            input_category=input_category,
            output_category=output_category,
            is_sensitive=is_sensitive,
            required_confirmation=required_confirmation,
            confirmed_by_user=confirmed_by_user,
            start_date=start_date,
            end_date=end_date,
            search=search,
        )

        cursor = (
            self.collection.find(query)
            .sort(sort_by, self._sort_direction(sort_order))
            .skip(skip)
            .limit(limit)
        )

        documents = await cursor.to_list(length=limit)
        return self._convert_many(documents)

    async def count_tool_logs(
        self,
        company_id: str = "default",
        tool_name: Optional[str] = None,
        status: Optional[str] = None,
        actor_id: Optional[str] = None,
        actor_type: Optional[str] = None,
        session_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        input_category: Optional[str] = None,
        output_category: Optional[str] = None,
        is_sensitive: Optional[bool] = None,
        required_confirmation: Optional[bool] = None,
        confirmed_by_user: Optional[bool] = None,
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
        search: Optional[str] = None,
    ) -> int:
        """
        Count tool logs with filters.
        """
        query = self._build_tool_query(
            company_id=company_id,
            tool_name=tool_name,
            status=status,
            actor_id=actor_id,
            actor_type=actor_type,
            session_id=session_id,
            conversation_id=conversation_id,
            request_id=request_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            input_category=input_category,
            output_category=output_category,
            is_sensitive=is_sensitive,
            required_confirmation=required_confirmation,
            confirmed_by_user=confirmed_by_user,
            start_date=start_date,
            end_date=end_date,
            search=search,
        )

        return await self.collection.count_documents(query)

    def _build_tool_query(
        self,
        company_id: str = "default",
        tool_name: Optional[str] = None,
        status: Optional[str] = None,
        actor_id: Optional[str] = None,
        actor_type: Optional[str] = None,
        session_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        input_category: Optional[str] = None,
        output_category: Optional[str] = None,
        is_sensitive: Optional[bool] = None,
        required_confirmation: Optional[bool] = None,
        confirmed_by_user: Optional[bool] = None,
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build common tool log query.
        """
        query: Dict[str, Any] = {
            "company_id": self._normalize_company_id(company_id),
        }

        filters = {
            "tool_name": tool_name,
            "status": status,
            "actor.actor_id": actor_id,
            "actor.actor_type": actor_type,
            "session_id": session_id,
            "conversation_id": conversation_id,
            "request_id": request_id,
            "correlation_id": correlation_id,
            "trace_id": trace_id,
            "input_category": input_category,
            "output_category": output_category,
        }

        for key, value in filters.items():
            value = self._normalize_text(value)
            if value is not None:
                query[key] = value

        if is_sensitive is not None:
            query["is_sensitive"] = is_sensitive

        if required_confirmation is not None:
            query["required_confirmation"] = required_confirmation

        if confirmed_by_user is not None:
            query["confirmed_by_user"] = confirmed_by_user

        query.update(
            self._date_range_query(
                field_name="started_at",
                start_date=start_date,
                end_date=end_date,
            )
        )

        search = self._normalize_text(search)
        if search:
            query["$or"] = [
                {"tool_name": {"$regex": search, "$options": "i"}},
                {"input_summary": {"$regex": search, "$options": "i"}},
                {"output_summary": {"$regex": search, "$options": "i"}},
                {"actor.actor_name": {"$regex": search, "$options": "i"}},
                {"error_message": {"$regex": search, "$options": "i"}},
                {"blocked_reason": {"$regex": search, "$options": "i"}},
            ]

        return query

    # -------------------------
    # Compatibility query helpers
    # -------------------------

    async def find_by_session(
        self,
        session_id: str,
        company_id: str = "default",
        limit: int = 100,
        skip: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Find all tool calls in a session.
        """
        return await self.list_tool_logs(
            company_id=company_id,
            session_id=session_id,
            limit=limit,
            skip=skip,
        )

    async def find_by_actor(
        self,
        actor_id: str,
        company_id: str = "default",
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
        limit: int = 100,
        skip: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Find tool logs by actor.
        """
        return await self.list_tool_logs(
            company_id=company_id,
            actor_id=actor_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            skip=skip,
        )

    async def find_by_tool_name(
        self,
        tool_name: str,
        company_id: str = "default",
        status: Optional[str] = None,
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
        limit: int = 100,
        skip: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Find tool logs by tool name.
        """
        return await self.list_tool_logs(
            company_id=company_id,
            tool_name=tool_name,
            status=status,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            skip=skip,
        )

    async def find_sensitive_tool_calls(
        self,
        company_id: str = "default",
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
        limit: int = 100,
        skip: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Find sensitive tool calls.
        """
        return await self.list_tool_logs(
            company_id=company_id,
            is_sensitive=True,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            skip=skip,
        )

    # -------------------------
    # Statistics
    # -------------------------

    async def get_statistics(
        self,
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
        company_id: str = "default",
    ) -> Dict[str, Any]:
        """
        Get tool log statistics.
        """
        match_stage: Dict[str, Any] = {
            "company_id": self._normalize_company_id(company_id),
        }

        if start_date or end_date:
            match_stage.update(
                self._date_range_query(
                    field_name="started_at",
                    start_date=start_date,
                    end_date=end_date,
                )
            )

        pipeline = [
            {"$match": match_stage},
            {
                "$facet": {
                    "total_count": [{"$count": "count"}],
                    "by_tool": [
                        {"$group": {"_id": "$tool_name", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}},
                        {"$limit": 20},
                    ],
                    "by_status": [
                        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}},
                    ],
                    "by_input_category": [
                        {"$group": {"_id": "$input_category", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}},
                    ],
                    "by_output_category": [
                        {"$group": {"_id": "$output_category", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}},
                    ],
                    "avg_latency": [
                        {"$match": {"latency_ms": {"$exists": True, "$ne": None}}},
                        {
                            "$group": {
                                "_id": None,
                                "avg_latency_ms": {"$avg": "$latency_ms"},
                                "max_latency_ms": {"$max": "$latency_ms"},
                            }
                        },
                    ],
                    "sensitive_count": [
                        {"$match": {"is_sensitive": True}},
                        {"$count": "count"},
                    ],
                    "confirmation_required_count": [
                        {"$match": {"required_confirmation": True}},
                        {"$count": "count"},
                    ],
                }
            },
        ]

        result = await self.collection.aggregate(pipeline).to_list(length=1)

        if not result:
            return self._empty_statistics(company_id)

        data = result[0]

        by_status = {
            item["_id"]: item["count"]
            for item in data.get("by_status", [])
            if item.get("_id") is not None
        }

        return {
            "company_id": self._normalize_company_id(company_id),
            "total_tool_calls": data["total_count"][0]["count"] if data["total_count"] else 0,
            "successful_tool_calls": by_status.get("success", 0),
            "failed_tool_calls": by_status.get("failed", 0),
            "blocked_tool_calls": by_status.get("blocked", 0),
            "timeout_tool_calls": by_status.get("timeout", 0),
            "sensitive_tool_calls": (
                data["sensitive_count"][0]["count"]
                if data["sensitive_count"]
                else 0
            ),
            "confirmation_required_calls": (
                data["confirmation_required_count"][0]["count"]
                if data["confirmation_required_count"]
                else 0
            ),
            "average_latency_ms": (
                data["avg_latency"][0]["avg_latency_ms"]
                if data["avg_latency"]
                else None
            ),
            "calls_by_tool": {
                item["_id"]: item["count"]
                for item in data.get("by_tool", [])
                if item.get("_id") is not None
            },
            "calls_by_status": by_status,
            "calls_by_input_category": {
                item["_id"]: item["count"]
                for item in data.get("by_input_category", [])
                if item.get("_id") is not None
            },
            "calls_by_output_category": {
                item["_id"]: item["count"]
                for item in data.get("by_output_category", [])
                if item.get("_id") is not None
            },
        }

    def _empty_statistics(self, company_id: str = "default") -> Dict[str, Any]:
        """
        Empty tool statistics.
        """
        return {
            "company_id": self._normalize_company_id(company_id),
            "total_tool_calls": 0,
            "successful_tool_calls": 0,
            "failed_tool_calls": 0,
            "blocked_tool_calls": 0,
            "timeout_tool_calls": 0,
            "sensitive_tool_calls": 0,
            "confirmation_required_calls": 0,
            "average_latency_ms": None,
            "calls_by_tool": {},
            "calls_by_status": {},
            "calls_by_input_category": {},
            "calls_by_output_category": {},
        }