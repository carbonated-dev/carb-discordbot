from peewee import IntegerField, BigIntegerField, DateTimeField, TextField
from playhouse.sqlite_ext import JSONField

from PunyBot.database import SQLiteBase


@SQLiteBase.register
class CollaborationRequest(SQLiteBase):
    class Meta:
        table_name = 'collaboration_request'

    id = IntegerField(primary_key=True)
    user_id = BigIntegerField()
    submission_date = DateTimeField()
    response = JSONField()
