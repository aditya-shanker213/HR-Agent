"""
Holiday repository - all MongoDB operations for holidays collection.

Pattern:
Route → Service → Repository → MongoDB

This repository handles:
- Create holiday
- Read holiday by id/date
- List holidays with filters/search/pagination
- Count holidays for pagination
- Update holiday
- Activate/deactivate holiday
- Bulk import support
- Calendar helpers
- Working day calculation helpers
- Holiday statistics

Important:
- Routes should not write MongoDB queries.
- Services should not write MongoDB queries.
- All holidays collection queries should go through this repository.
"""

from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple
import re

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError


class HolidayRepository:
    """
    Repository for holidays collection.

    This class is responsible only for database operations.
    Business rules should stay in service layer.
    """

    VALID_HOLIDAY_TYPES = {
        "national",
        "festival",
        "company",
        "optional",
        "regional",
    }

    VALID_SORT_FIELDS = {
        "date",
        "name",
        "type",
        "year",
        "location",
        "display_order",
        "created_at",
        "updated_at",
    }

    BLOCKED_UPDATE_FIELDS = {
        "_id",
        "id",
        "created_at",
        "created_by",
    }

    OPTIONAL_TEXT_FIELDS = {
        "description",
        "location",
        "created_by",
        "updated_by",
    }

    COMPANY_WIDE_LOCATION_VALUES = [None, "", "All"]

    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.holidays

    # -------------------------
    # Internal helpers
    # -------------------------

    def _normalize_type(self, holiday_type: Optional[str]) -> str:
        """
        Normalize holiday type to lowercase.

        Repository normalizes only.
        Final validation should also happen in model/service layer.
        """
        if not holiday_type:
            return "national"

        holiday_type = str(holiday_type).strip().lower()

        if holiday_type not in self.VALID_HOLIDAY_TYPES:
            raise ValueError(
                "Holiday type must be one of: "
                f"{', '.join(sorted(self.VALID_HOLIDAY_TYPES))}"
            )

        return holiday_type

    def _normalize_location(self, location: Optional[str]) -> Optional[str]:
        """
        Normalize location.

        Rules:
        - None, empty string, and 'all' mean company-wide.
        - Company-wide is stored as None.
        - Other locations keep their original readable formatting.
        """
        if location is None:
            return None

        location = str(location).strip()

        if not location:
            return None

        if location.lower() == "all":
            return None

        return location

    def _normalize_optional_text(self, value: Optional[str]) -> Optional[str]:
        """
        Strip optional text and convert empty string to None.
        """
        if value is None:
            return None

        value = str(value).strip()
        return value or None

    def _to_object_id(self, value: str) -> Optional[ObjectId]:
        """
        Safely convert string ID to MongoDB ObjectId.
        """
        try:
            return ObjectId(str(value))
        except (InvalidId, TypeError):
            return None

    def _date_to_datetime(self, value: Any) -> datetime:
        """
        Convert date/datetime/string to datetime for MongoDB storage.

        MongoDB BSON supports datetime, not pure Python date.
        This stores the holiday date at midnight.
        """
        if isinstance(value, datetime):
            return datetime.combine(value.date(), time.min)

        if isinstance(value, date):
            return datetime.combine(value, time.min)

        if isinstance(value, str):
            parsed_date = date.fromisoformat(value)
            return datetime.combine(parsed_date, time.min)

        raise ValueError("date must be a date, datetime, or ISO date string")

    def _datetime_to_date(self, value: Any) -> Any:
        """
        Convert MongoDB datetime back to Python date for API response.

        If value is already a date, return it as-is.
        """
        if isinstance(value, datetime):
            return value.date()

        return value

    def _convert_id(
        self,
        document: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Convert MongoDB ObjectId to string and MongoDB datetime date to date.

        Keeps both:
        - _id for internal consistency
        - id for API/service convenience
        """
        if not document:
            return None

        if "_id" in document:
            document["_id"] = str(document["_id"])
            document["id"] = document["_id"]

        if "date" in document:
            document["date"] = self._datetime_to_date(document["date"])

        return document

    def _convert_many_ids(
        self,
        documents: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Convert ObjectId to string for a list of documents.
        """
        converted_documents: List[Dict[str, Any]] = []

        for document in documents:
            converted = self._convert_id(document)
            if converted is not None:
                converted_documents.append(converted)

        return converted_documents

    def _location_match_query(self, location: Optional[str]) -> Dict[str, Any]:
        """
        Build location query.

        If location is provided, return both:
        - company-wide holidays
        - location-specific holidays
        """
        normalized_location = self._normalize_location(location)

        if normalized_location is None:
            return {
                "$or": [
                    {"location": None},
                    {"location": ""},
                    {"location": "All"},
                ]
            }

        return {
            "$or": [
                {"location": None},
                {"location": ""},
                {"location": "All"},
                {"location": normalized_location},
            ]
        }

    def _clean_insert_data(self, holiday_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize holiday data before insert.
        """
        cleaned = dict(holiday_data)

        if "date" not in cleaned or cleaned["date"] is None:
            raise ValueError("date is required")

        cleaned["date"] = self._date_to_datetime(cleaned["date"])
        cleaned["year"] = int(cleaned.get("year") or cleaned["date"].year)

        cleaned["type"] = self._normalize_type(cleaned.get("type"))
        cleaned["location"] = self._normalize_location(cleaned.get("location"))

        for field in self.OPTIONAL_TEXT_FIELDS:
            if field in cleaned and field != "location":
                cleaned[field] = self._normalize_optional_text(cleaned[field])

        cleaned.setdefault("is_working_day", False)
        cleaned.setdefault("is_half_day", False)
        cleaned.setdefault("is_optional", False)
        cleaned.setdefault("optional_limit_per_employee", None)
        cleaned.setdefault("display_order", 0)
        cleaned.setdefault("is_active", True)

        if cleaned["type"] == "optional":
            cleaned["is_optional"] = True

        if cleaned["is_optional"]:
            cleaned["type"] = "optional"

        now = datetime.utcnow()
        cleaned["created_at"] = now
        cleaned["updated_at"] = now

        return cleaned

    def _clean_update_data(self, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove fields that should never be updated directly.
        Normalize type, date, location, and optional text fields.
        """
        cleaned: Dict[str, Any] = {}

        for key, value in update_data.items():
            if key in self.BLOCKED_UPDATE_FIELDS:
                continue

            cleaned[key] = value

        if "date" in cleaned and cleaned["date"] is not None:
            cleaned["date"] = self._date_to_datetime(cleaned["date"])

            if "year" not in cleaned or cleaned.get("year") is None:
                cleaned["year"] = cleaned["date"].year

        if "year" in cleaned and cleaned["year"] is not None:
            cleaned["year"] = int(cleaned["year"])

        if "type" in cleaned and cleaned["type"] is not None:
            cleaned["type"] = self._normalize_type(cleaned["type"])

        if "location" in cleaned:
            cleaned["location"] = self._normalize_location(cleaned.get("location"))

        for field in self.OPTIONAL_TEXT_FIELDS:
            if field in cleaned and field != "location":
                cleaned[field] = self._normalize_optional_text(cleaned[field])

        if cleaned.get("type") == "optional":
            cleaned["is_optional"] = True

        if cleaned.get("is_optional") is True:
            cleaned["type"] = "optional"

        cleaned["updated_at"] = datetime.utcnow()

        return cleaned

    def _build_filter_query(
        self,
        year: Optional[int] = None,
        month: Optional[int] = None,
        holiday_type: Optional[str] = None,
        location: Optional[str] = None,
        is_optional: Optional[bool] = None,
        is_working_day: Optional[bool] = None,
        is_half_day: Optional[bool] = None,
        is_active: Optional[bool] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build MongoDB query for list/count operations.

        Important:
        Uses $and so location $or and search $or do not overwrite each other.
        """
        query: Dict[str, Any] = {}
        and_conditions: List[Dict[str, Any]] = []

        if year is not None:
            query["year"] = int(year)

        if month is not None:
            if month < 1 or month > 12:
                raise ValueError("month must be between 1 and 12")

            query["$expr"] = {
                "$eq": [{"$month": "$date"}, month]
            }

        if holiday_type:
            query["type"] = self._normalize_type(holiday_type)

        if location:
            and_conditions.append(self._location_match_query(location))

        if is_optional is not None:
            query["is_optional"] = is_optional

        if is_working_day is not None:
            query["is_working_day"] = is_working_day

        if is_half_day is not None:
            query["is_half_day"] = is_half_day

        if is_active is not None:
            query["is_active"] = is_active

        if from_date or to_date:
            date_query: Dict[str, Any] = {}

            if from_date:
                date_query["$gte"] = self._date_to_datetime(from_date)

            if to_date:
                date_query["$lte"] = self._date_to_datetime(to_date)

            query["date"] = date_query

        if search:
            search_text = search.strip()

            if search_text:
                safe_search = re.escape(search_text)
                and_conditions.append(
                    {
                        "$or": [
                            {"name": {"$regex": safe_search, "$options": "i"}},
                            {"type": {"$regex": safe_search, "$options": "i"}},
                            {"location": {"$regex": safe_search, "$options": "i"}},
                            {"description": {"$regex": safe_search, "$options": "i"}},
                        ]
                    }
                )

        if and_conditions:
            query["$and"] = and_conditions

        return query

    # -------------------------
    # Create
    # -------------------------

    async def create(self, holiday_data: Dict[str, Any]) -> str:
        """
        Create a new holiday.

        Returns:
            Created holiday _id as string.

        Raises:
            DuplicateKeyError if a unique holiday index is violated.
        """
        cleaned_data = self._clean_insert_data(holiday_data)

        try:
            result = await self.collection.insert_one(cleaned_data)
            return str(result.inserted_id)
        except DuplicateKeyError:
            raise

    # -------------------------
    # Find operations
    # -------------------------

    async def find_by_id(self, holiday_id: str) -> Optional[Dict[str, Any]]:
        """
        Find holiday by MongoDB _id.
        """
        object_id = self._to_object_id(holiday_id)

        if object_id is None:
            return None

        holiday = await self.collection.find_one({"_id": object_id})
        return self._convert_id(holiday)

    async def find_active_by_id(
        self,
        holiday_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Find active holiday by MongoDB _id.
        """
        object_id = self._to_object_id(holiday_id)

        if object_id is None:
            return None

        holiday = await self.collection.find_one(
            {
                "_id": object_id,
                "is_active": True,
            }
        )

        return self._convert_id(holiday)

    async def find_by_date(
        self,
        holiday_date: date,
        location: Optional[str] = None,
        include_working_days: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """
        Find holiday by date and optional location.
        """
        query: Dict[str, Any] = {
            "date": self._date_to_datetime(holiday_date),
            "is_active": True,
        }

        and_conditions: List[Dict[str, Any]] = []

        if location:
            and_conditions.append(self._location_match_query(location))

        if not include_working_days:
            query["is_working_day"] = False

        if and_conditions:
            query["$and"] = and_conditions

        holiday = await self.collection.find_one(
            query,
            sort=[
                ("location", DESCENDING),
                ("display_order", ASCENDING),
                ("name", ASCENDING),
            ],
        )

        return self._convert_id(holiday)

    async def find_holidays_in_range(
        self,
        from_date: date,
        to_date: date,
        location: Optional[str] = None,
        exclude_working_days: bool = True,
        include_optional: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Find all holidays within a date range.

        Used for leave working day calculation.
        """
        query: Dict[str, Any] = {
            "date": {
                "$gte": self._date_to_datetime(from_date),
                "$lte": self._date_to_datetime(to_date),
            },
            "is_active": True,
        }

        and_conditions: List[Dict[str, Any]] = []

        if exclude_working_days:
            query["is_working_day"] = False

        if not include_optional:
            query["is_optional"] = False

        if location:
            and_conditions.append(self._location_match_query(location))

        if and_conditions:
            query["$and"] = and_conditions

        cursor = self.collection.find(query).sort(
            [
                ("date", ASCENDING),
                ("display_order", ASCENDING),
                ("name", ASCENDING),
            ]
        )

        holidays = await cursor.to_list(length=2000)
        return self._convert_many_ids(holidays)

    async def exists_by_id(self, holiday_id: str) -> bool:
        """
        Check whether holiday exists by ID.
        """
        object_id = self._to_object_id(holiday_id)

        if object_id is None:
            return False

        count = await self.collection.count_documents({"_id": object_id}, limit=1)
        return count > 0

    async def active_exists_by_id(self, holiday_id: str) -> bool:
        """
        Check whether active holiday exists by ID.
        """
        object_id = self._to_object_id(holiday_id)

        if object_id is None:
            return False

        count = await self.collection.count_documents(
            {
                "_id": object_id,
                "is_active": True,
            },
            limit=1,
        )

        return count > 0

    async def duplicate_exists(
        self,
        holiday_date: date,
        name: str,
        location: Optional[str] = None,
        exclude_id: Optional[str] = None,
    ) -> bool:
        """
        Check if a holiday with same date, name, and location already exists.

        Service can use this before create/update.
        """
        query: Dict[str, Any] = {
            "date": self._date_to_datetime(holiday_date),
            "name": str(name).strip(),
            "location": self._normalize_location(location),
        }

        if exclude_id:
            object_id = self._to_object_id(exclude_id)

            if object_id is None:
                return False

            query["_id"] = {"$ne": object_id}

        count = await self.collection.count_documents(query, limit=1)
        return count > 0

    async def is_holiday(
        self,
        check_date: date,
        location: Optional[str] = None,
        exclude_working_days: bool = True,
        include_optional: bool = True,
    ) -> bool:
        """
        Check if a given date is a holiday.

        Used for working day validation.
        """
        query: Dict[str, Any] = {
            "date": self._date_to_datetime(check_date),
            "is_active": True,
        }

        and_conditions: List[Dict[str, Any]] = []

        if exclude_working_days:
            query["is_working_day"] = False

        if not include_optional:
            query["is_optional"] = False

        if location:
            and_conditions.append(self._location_match_query(location))

        if and_conditions:
            query["$and"] = and_conditions

        count = await self.collection.count_documents(query, limit=1)
        return count > 0

    # -------------------------
    # List and search
    # -------------------------

    async def list_all(
        self,
        year: Optional[int] = None,
        month: Optional[int] = None,
        holiday_type: Optional[str] = None,
        location: Optional[str] = None,
        is_optional: Optional[bool] = None,
        is_working_day: Optional[bool] = None,
        is_half_day: Optional[bool] = None,
        is_active: Optional[bool] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        search: Optional[str] = None,
        sort_by: str = "date",
        sort_order: str = "asc",
        skip: int = 0,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        List holidays with filtering, search, sorting, and pagination.
        """
        query = self._build_filter_query(
            year=year,
            month=month,
            holiday_type=holiday_type,
            location=location,
            is_optional=is_optional,
            is_working_day=is_working_day,
            is_half_day=is_half_day,
            is_active=is_active,
            from_date=from_date,
            to_date=to_date,
            search=search,
        )

        if sort_by not in self.VALID_SORT_FIELDS:
            sort_by = "date"

        sort_direction = ASCENDING if sort_order.lower() == "asc" else DESCENDING

        safe_skip = max(skip, 0)
        safe_limit = min(max(limit, 1), 500)

        cursor = (
            self.collection.find(query)
            .sort(
                [
                    (sort_by, sort_direction),
                    ("display_order", ASCENDING),
                    ("name", ASCENDING),
                ]
            )
            .skip(safe_skip)
            .limit(safe_limit)
        )

        holidays = await cursor.to_list(length=safe_limit)
        return self._convert_many_ids(holidays)

    async def list_for_calendar(
        self,
        year: int,
        month: Optional[int] = None,
        location: Optional[str] = None,
        include_optional: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        List active holidays for frontend calendar.

        If month is provided, returns only that month.
        Otherwise returns full year.
        """
        return await self.list_all(
            year=year,
            month=month,
            location=location,
            is_active=True,
            is_optional=None if include_optional else False,
            sort_by="date",
            sort_order="asc",
            skip=0,
            limit=500,
        )

    async def list_upcoming_holidays(
        self,
        days: int = 30,
        location: Optional[str] = None,
        include_optional: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        List upcoming holidays for the next N days.

        Used for employee dashboard.
        """
        safe_days = min(max(days, 1), 365)
        today = date.today()
        end_date = today + timedelta(days=safe_days)

        return await self.find_holidays_in_range(
            from_date=today,
            to_date=end_date,
            location=location,
            exclude_working_days=False,
            include_optional=include_optional,
        )

    async def count(
        self,
        year: Optional[int] = None,
        month: Optional[int] = None,
        holiday_type: Optional[str] = None,
        location: Optional[str] = None,
        is_optional: Optional[bool] = None,
        is_working_day: Optional[bool] = None,
        is_half_day: Optional[bool] = None,
        is_active: Optional[bool] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        search: Optional[str] = None,
    ) -> int:
        """
        Count holidays matching filters.

        Useful for pagination metadata.
        """
        query = self._build_filter_query(
            year=year,
            month=month,
            holiday_type=holiday_type,
            location=location,
            is_optional=is_optional,
            is_working_day=is_working_day,
            is_half_day=is_half_day,
            is_active=is_active,
            from_date=from_date,
            to_date=to_date,
            search=search,
        )

        return await self.collection.count_documents(query)

    # -------------------------
    # Update
    # -------------------------

    async def update(
        self,
        holiday_id: str,
        update_data: Dict[str, Any],
    ) -> bool:
        """
        Update holiday fields.

        Returns:
            True if holiday exists and update operation matched it.
        """
        object_id = self._to_object_id(holiday_id)

        if object_id is None:
            return False

        safe_update = self._clean_update_data(update_data)

        if not safe_update:
            return False

        result = await self.collection.update_one(
            {"_id": object_id},
            {"$set": safe_update},
        )

        return result.matched_count > 0

    async def update_many_display_order(
        self,
        order_updates: List[Dict[str, Any]],
        updated_by: Optional[str] = None,
    ) -> Tuple[int, List[Dict[str, Any]]]:
        """
        Update display_order for multiple holidays.

        Expected item format:
        {
            "id": "holiday_id",
            "display_order": 1
        }
        """
        updated_count = 0
        errors: List[Dict[str, Any]] = []

        for index, item in enumerate(order_updates):
            holiday_id = item.get("id") or item.get("_id")
            display_order = item.get("display_order")

            if holiday_id is None or display_order is None:
                errors.append(
                    {
                        "index": index,
                        "error": "id and display_order are required",
                    }
                )
                continue

            object_id = self._to_object_id(str(holiday_id))

            if object_id is None:
                errors.append(
                    {
                        "index": index,
                        "id": holiday_id,
                        "error": "Invalid holiday ID",
                    }
                )
                continue

            try:
                safe_display_order = max(int(display_order), 0)
            except (TypeError, ValueError):
                errors.append(
                    {
                        "index": index,
                        "id": holiday_id,
                        "error": "display_order must be a valid integer",
                    }
                )
                continue

            update_data: Dict[str, Any] = {
                "display_order": safe_display_order,
                "updated_at": datetime.utcnow(),
            }

            if updated_by:
                update_data["updated_by"] = self._normalize_optional_text(updated_by)

            result = await self.collection.update_one(
                {"_id": object_id},
                {"$set": update_data},
            )

            if result.matched_count > 0:
                updated_count += 1
            else:
                errors.append(
                    {
                        "index": index,
                        "id": holiday_id,
                        "error": "Holiday not found",
                    }
                )

        return updated_count, errors

    # -------------------------
    # Activate / deactivate
    # -------------------------

    async def deactivate(
        self,
        holiday_id: str,
        updated_by: Optional[str] = None,
    ) -> bool:
        """
        Soft delete holiday by setting is_active=False.

        The document remains in MongoDB.
        """
        object_id = self._to_object_id(holiday_id)

        if object_id is None:
            return False

        update_data: Dict[str, Any] = {
            "is_active": False,
            "updated_at": datetime.utcnow(),
        }

        if updated_by:
            update_data["updated_by"] = self._normalize_optional_text(updated_by)

        result = await self.collection.update_one(
            {"_id": object_id},
            {"$set": update_data},
        )

        return result.matched_count > 0

    async def activate(
        self,
        holiday_id: str,
        updated_by: Optional[str] = None,
    ) -> bool:
        """
        Reactivate a deactivated holiday.
        """
        object_id = self._to_object_id(holiday_id)

        if object_id is None:
            return False

        update_data: Dict[str, Any] = {
            "is_active": True,
            "updated_at": datetime.utcnow(),
        }

        if updated_by:
            update_data["updated_by"] = self._normalize_optional_text(updated_by)

        result = await self.collection.update_one(
            {"_id": object_id},
            {"$set": update_data},
        )

        return result.matched_count > 0

    # -------------------------
    # Bulk operations
    # -------------------------

    async def create_many(
        self,
        holidays: List[Dict[str, Any]],
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        """
        Create multiple holidays.

        Returns:
            Tuple of:
            - created_ids
            - errors

        This keeps per-record error reporting, useful for bulk import UI.
        """
        created_ids: List[str] = []
        errors: List[Dict[str, Any]] = []

        for index, holiday_data in enumerate(holidays):
            try:
                created_id = await self.create(holiday_data)
                created_ids.append(created_id)

            except DuplicateKeyError:
                errors.append(
                    {
                        "index": index,
                        "date": str(holiday_data.get("date")),
                        "name": holiday_data.get("name"),
                        "error": "Holiday already exists",
                    }
                )

            except Exception as exc:
                errors.append(
                    {
                        "index": index,
                        "date": str(holiday_data.get("date")),
                        "name": holiday_data.get("name"),
                        "error": str(exc),
                    }
                )

        return created_ids, errors

    # -------------------------
    # Working day helpers
    # -------------------------

    async def get_non_working_holiday_dates(
        self,
        from_date: date,
        to_date: date,
        location: Optional[str] = None,
        include_optional: bool = False,
    ) -> set[date]:
        """
        Return non-working holiday dates in a range.

        Useful for leave and payroll calculations.
        """
        holidays = await self.find_holidays_in_range(
            from_date=from_date,
            to_date=to_date,
            location=location,
            exclude_working_days=True,
            include_optional=include_optional,
        )

        return {
            holiday["date"]
            for holiday in holidays
            if holiday.get("date") is not None
        }

    async def count_working_days(
        self,
        from_date: date,
        to_date: date,
        location: Optional[str] = None,
        exclude_weekends: bool = True,
        include_optional_holidays: bool = False,
    ) -> int:
        """
        Count working days between two dates.

        Excludes:
        - Holidays where is_working_day=False
        - Weekends Saturday/Sunday if exclude_weekends=True

        Used for leave deduction calculation.
        """
        if from_date > to_date:
            return 0

        holiday_dates = await self.get_non_working_holiday_dates(
            from_date=from_date,
            to_date=to_date,
            location=location,
            include_optional=include_optional_holidays,
        )

        working_days = 0
        current_date = from_date

        while current_date <= to_date:
            is_weekend = exclude_weekends and current_date.weekday() >= 5
            is_holiday = current_date in holiday_dates

            if not is_weekend and not is_holiday:
                working_days += 1

            current_date += timedelta(days=1)

        return working_days

    async def calculate_leave_days(
        self,
        from_date: date,
        to_date: date,
        location: Optional[str] = None,
        exclude_weekends: bool = True,
        include_optional_holidays: bool = False,
    ) -> Dict[str, Any]:
        """
        Return detailed leave-day calculation.

        Useful later for leave service and AI explanation.
        """
        if from_date > to_date:
            return {
                "calendar_days": 0,
                "working_days": 0,
                "holiday_dates": [],
                "weekend_dates": [],
            }

        holiday_dates = await self.get_non_working_holiday_dates(
            from_date=from_date,
            to_date=to_date,
            location=location,
            include_optional=include_optional_holidays,
        )

        weekend_dates: List[date] = []
        working_days = 0
        current_date = from_date

        while current_date <= to_date:
            is_weekend = exclude_weekends and current_date.weekday() >= 5
            is_holiday = current_date in holiday_dates

            if is_weekend:
                weekend_dates.append(current_date)

            if not is_weekend and not is_holiday:
                working_days += 1

            current_date += timedelta(days=1)

        return {
            "calendar_days": (to_date - from_date).days + 1,
            "working_days": working_days,
            "holiday_dates": sorted(list(holiday_dates)),
            "weekend_dates": weekend_dates,
        }

    # -------------------------
    # Statistics
    # -------------------------

    async def get_statistics(
        self,
        year: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get holiday statistics for admin dashboard.
        """
        query: Dict[str, Any] = {}

        if year:
            query["year"] = int(year)

        total = await self.collection.count_documents(query)
        active = await self.collection.count_documents({**query, "is_active": True})
        inactive = total - active

        national = await self.collection.count_documents(
            {**query, "type": "national", "is_active": True}
        )

        festival = await self.collection.count_documents(
            {**query, "type": "festival", "is_active": True}
        )

        company = await self.collection.count_documents(
            {**query, "type": "company", "is_active": True}
        )

        optional = await self.collection.count_documents(
            {**query, "type": "optional", "is_active": True}
        )

        regional = await self.collection.count_documents(
            {**query, "type": "regional", "is_active": True}
        )

        working_day = await self.collection.count_documents(
            {**query, "is_working_day": True, "is_active": True}
        )

        non_working_day = await self.collection.count_documents(
            {**query, "is_working_day": False, "is_active": True}
        )

        half_day = await self.collection.count_documents(
            {**query, "is_half_day": True, "is_active": True}
        )

        location_specific = await self.collection.count_documents(
            {
                **query,
                "is_active": True,
                "location": {"$nin": self.COMPANY_WIDE_LOCATION_VALUES},
            }
        )

        company_wide = await self.collection.count_documents(
            {
                **query,
                "is_active": True,
                "$or": [
                    {"location": None},
                    {"location": ""},
                    {"location": "All"},
                ],
            }
        )

        # Holidays per year
        year_pipeline = [
            {"$match": {"is_active": True}},
            {
                "$group": {
                    "_id": "$year",
                    "count": {"$sum": 1},
                }
            },
            {"$sort": {"_id": 1}},
        ]

        year_counts = await self.collection.aggregate(year_pipeline).to_list(length=100)

        holidays_per_year = {
            int(item["_id"]): item["count"]
            for item in year_counts
            if item.get("_id") is not None
        }

        # Holidays per location
        location_pipeline = [
            {"$match": {"is_active": True}},
            {
                "$group": {
                    "_id": {
                        "$ifNull": ["$location", "All"],
                    },
                    "count": {"$sum": 1},
                }
            },
            {"$sort": {"_id": 1}},
        ]

        location_counts = await self.collection.aggregate(location_pipeline).to_list(
            length=500
        )

        holidays_per_location = {
            str(item["_id"] or "All"): item["count"]
            for item in location_counts
        }

        return {
            "total_holidays": total,
            "active_holidays": active,
            "inactive_holidays": inactive,
            "national_holidays": national,
            "festival_holidays": festival,
            "company_holidays": company,
            "optional_holidays": optional,
            "regional_holidays": regional,
            "working_day_holidays": working_day,
            "non_working_day_holidays": non_working_day,
            "half_day_holidays": half_day,
            "location_specific_holidays": location_specific,
            "company_wide_holidays": company_wide,
            "holidays_per_year": holidays_per_year,
            "holidays_per_location": holidays_per_location,
        }