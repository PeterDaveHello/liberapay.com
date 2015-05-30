from contextlib import contextmanager

from postgres import Postgres


@contextmanager
def just_yield(obj):
    yield obj


class DB(Postgres):

    def get_cursor(self, cursor=None, **kw):
        if cursor:
            if kw:
                raise ValueError('cannot change options when reusing a cursor')
            return just_yield(cursor)
        return super(DB, self).get_cursor(**kw)

    def self_check(self):
        with self.get_cursor() as cursor:
            check_db(cursor)


def check_db(cursor):
    """Runs all available self checks on the given cursor.
    """
    _check_balances(cursor)
    _check_tips(cursor)
    _check_orphans(cursor)
    _check_orphans_no_tips(cursor)
    _check_paydays_volumes(cursor)


def _check_tips(cursor):
    """
    Checks that there are no rows in tips with duplicate (tipper, tippee, mtime).

    https://github.com/gratipay/gratipay.com/issues/1704
    """
    conflicting_tips = cursor.one("""
        SELECT count(*)
          FROM
             (
                SELECT * FROM tips
                EXCEPT
                SELECT DISTINCT ON(tipper, tippee, mtime) *
                  FROM tips
              ORDER BY tipper, tippee, mtime
              ) AS foo
    """)
    assert conflicting_tips == 0


def _check_balances(cursor):
    """
    Recalculates balances for all participants from transfers and exchanges.

    https://github.com/gratipay/gratipay.com/issues/1118
    """
    b = cursor.all("""
        select p.id, expected, balance as actual
          from (
            select id, sum(a) as expected
              from (
                      select participant as id, sum(amount) as a
                        from exchanges
                       where amount > 0
                         and (status is null or status = 'succeeded')
                    group by participant

                       union all

                      select participant as id, sum(amount-fee) as a
                        from exchanges
                       where amount < 0
                         and (status is null or status <> 'failed')
                    group by participant

                       union all

                      select tipper as id, sum(-amount) as a
                        from transfers
                    group by tipper

                       union all

                      select tippee as id, sum(amount) as a
                        from transfers
                    group by tippee
                    ) as foo
            group by id
          ) as foo2
        join participants p on p.id = foo2.id
        where expected <> p.balance
    """)
    assert len(b) == 0, "conflicting balances: {}".format(b)


def _check_orphans(cursor):
    """Finds non-archived participants that don't have an elsewhere account.
    """
    orphans = cursor.all("""
        select username
          from participants p
         where status != 'archived'
           and not exists (select * from elsewhere e where e.participant=p.id)
    """)
    assert len(orphans) == 0, "missing elsewheres: {}".format(list(orphans))


def _check_orphans_no_tips(cursor):
    """
    Finds participants
        * without elsewhere account attached
        * having non zero outstanding tip

    This should not happen because when we remove the last elsewhere account
    in take_over we also zero out all tips.
    """
    orphans_with_tips = cursor.all("""
        WITH valid_tips AS (SELECT * FROM current_tips WHERE amount > 0)
        SELECT id
          FROM (SELECT tipper AS id FROM valid_tips
                UNION
                SELECT tippee AS id FROM valid_tips) p
         WHERE NOT EXISTS (SELECT 1 FROM elsewhere WHERE participant=p.id)
    """)
    assert len(orphans_with_tips) == 0, orphans_with_tips


def _check_paydays_volumes(cursor):
    """
    Recalculate *_volume fields in paydays table using exchanges table.
    """
    if cursor.one("select exists (select * from paydays where ts_end < ts_start) as running"):
        # payday is running
        return
    charge_volume = cursor.all("""
        select * from (
            select id, ts_start, charge_volume, (
                    select coalesce(sum(amount+fee), 0)
                    from exchanges
                    where timestamp > ts_start
                    and timestamp < ts_end
                    and amount > 0
                    and recorder is null
                    and (status is null or status <> 'failed')
                ) as ref
            from paydays
            order by id
        ) as foo
        where charge_volume != ref
    """)
    assert len(charge_volume) == 0

    charge_fees_volume = cursor.all("""
        select * from (
            select id, ts_start, charge_fees_volume, (
                    select coalesce(sum(fee), 0)
                    from exchanges
                    where timestamp > ts_start
                    and timestamp < ts_end
                    and amount > 0
                    and recorder is null
                    and (status is null or status <> 'failed')
                ) as ref
            from paydays
            order by id
        ) as foo
        where charge_fees_volume != ref
    """)
    assert len(charge_fees_volume) == 0

    ach_volume = cursor.all("""
        select * from (
            select id, ts_start, ach_volume, (
                    select coalesce(sum(amount), 0)
                    from exchanges
                    where timestamp > ts_start
                    and timestamp < ts_end
                    and amount < 0
                    and recorder is null
                ) as ref
            from paydays
            order by id
        ) as foo
        where ach_volume != ref
    """)
    assert len(ach_volume) == 0

    ach_fees_volume = cursor.all("""
        select * from (
            select id, ts_start, ach_fees_volume, (
                    select coalesce(sum(fee), 0)
                    from exchanges
                    where timestamp > ts_start
                    and timestamp < ts_end
                    and amount < 0
                    and recorder is null
                ) as ref
            from paydays
            order by id
        ) as foo
        where ach_fees_volume != ref
    """)
    assert len(ach_fees_volume) == 0