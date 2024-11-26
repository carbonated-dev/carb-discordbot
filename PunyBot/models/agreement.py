import datetime
from peewee import BigIntegerField, DateTimeField, TextField

from PunyBot.database import SQLiteBase


@SQLiteBase.register
class Agreement(SQLiteBase):
    class Meta:
        table_name = 'agreement_submissions'

    user_id = BigIntegerField()
    creed_agree = TextField()
    signed_date = DateTimeField(default=datetime.datetime.now(datetime.UTC))
