from peewee import IntegerField, BigIntegerField, DateTimeField, TextField
from playhouse.sqlite_ext import JSONField

from PunyBot.database import SQLiteBase


class TicketStatus:
    OPEN = 1
    CLOSED = 2
    ON_HOLD = 3


@SQLiteBase.register
class SupportTicket(SQLiteBase):
    class Meta:
        table_name = 'support_tickets'

    id = IntegerField(primary_key=True)
    user_id = BigIntegerField()
    submission_date = DateTimeField()
    ticket_subject = TextField()
    ticket_description = TextField()
    ticket_extra = JSONField()
    ticket_status = IntegerField(default=TicketStatus.OPEN)

