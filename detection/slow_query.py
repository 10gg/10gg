import re
import subprocess
import json
import os
from log_entry import entry
from log_entry import parser

RE_TIDB_SLOW_QUERY = [
    re.compile(r".*cost_time:([^\s]*)"),
    re.compile(r".*backoff_time:([^\s]*)"),
    re.compile(r".*process_time:([^\s]*)"),
    re.compile(r".*total_keys:(\d+)"),
    re.compile(r".*processed_keys:(\d+)"),
    re.compile(r".*succ:((?:true|flase))\s+"),
    re.compile(r".*conn:(\d+)"),
    re.compile(r".*txn_start_ts:(\d+)\s+"),
    re.compile(r".*database:([^\s]*)"),
    re.compile(r".*table_id:(\d+)"),
    re.compile(r".*sql:(.*)"),
]


class SlowQuery(object):
    def __init__(self, logs=None, **args):
        self.cost_time = args['cost_time']
        self.process_time = args['process_time']
        self.backoff_time = args['backoff_time']
        self.process_keys = args['processed_keys']
        self.total_keys = args['total_keys']
        self.suss = args['suss']
        self.connect_id = args['connect_id']
        self.start_ts = args['start_ts']
        self.database = args['database']
        self.table_id = args['table_id']
        self.sql = args['sql']
        if logs is not None:
            self.take_relative_tikv_log(logs)

    def take_relative_tikv_log(self, logs):
        l = [s['content'] for s in entry.filter_by_word(logs, self.start_ts)]
        self.attach = "\n".join(l)

    def hit(self):
        if self.total_keys == "" or self.process_keys == "":
            return 0
        return float(self.process_keys)/float(self.total_keys)

    def status(self):
        return self.suss

    def suggestion(self):
        if self.hit() < 0.6:
            return "maybe too many version, check the GC interval"
        # TODO process time
        return None

    def rewrite(self):
        p1 = subprocess.Popen(["echo", self.sql], stdout=subprocess.PIPE)
        p2 = subprocess.Popen([os.path.join(os.path.dirname(__file__),
                                            '../bin/soar')], stdin=p1.stdout, stdout=subprocess.PIPE)
        res = p2.communicate()[0].decode('utf-8')
        return res

    def display(self):
        return {
            "status": self.status(),
            "cost_time": self.cost_time,
            "process_time": self.process_time,
            "backoff_time": self.backoff_time,
            "total_keys": self.total_keys,
            "process_keys": self.process_keys,
            "hit": format(self.hit(), ".2%"),
            "report": self.suggestion(),
            "relative_logs": self.attach,
            "rewrite": self.rewrite().strip().replace('\n', ' '),
        }


def take_slow_query_in_tidb(log, addition=None):
    content = log['content'].strip()
    r = []
    for reg in RE_TIDB_SLOW_QUERY:
        match = reg.match(content)
        if match is None:
            r.append("")
        else:
            print(match.groups())
            r.append(match.groups()[0])
    return SlowQuery(**{
        'cost_time': r[0],
        'process_time': r[1],
        'backoff_time': r[2],
        'total_keys': r[3],
        'processed_keys': r[4],
        'suss': r[5],
        'connect_id': r[6],
        'start_ts': r[7],
        'database': r[8],
        'table_id': r[9],
        'sql': r[10],
    }, logs=addition)


def slow_query_detect(tidb_logs, tikv_logs):
    tidb_slow = entry.filter_by_word(tidb_logs, "SLOW_QUERY")
    tikv_slow = entry.filter_by_word(tikv_logs, entry.TIKV_SLOW_QUERY)
    resp = []
    for log in tidb_slow:
        res = take_slow_query_in_tidb(log, tikv_slow)
        if res is not None:
            resp.append(res.display())
    return resp


if __name__ == "__main__":
    tidb_logs = [
        r'2018/12/01 19:07:40.985 adapter.go:390: [warning] [SLOW_QUERY] cost_time:600.339872ms process_time:914ms backoff_time:152ms request_count:3 total_keys:1090763 processed_keys:1000908 succ:true con:478 user:root@192.168.199.181 txn_start_ts:404661852013068325 database:sbtest1 table_ids:[33],sql:select count(*) from sbtest1',
        r"2018/05/29 16:47:06.810 adapter.go:353: [warning] [SLOW_QUERY] cost_time:17m20.253348972s succ:false connection_id:5281 txn_start_ts:400446609561747458 database:dbmlog table_ids:[57] index_ids:[2] sql:select id, type, number, remain, w_time, order_num, account_type, remark from money_log where account_type='s_money' and userid='359004'"]
    tikv_logs = [r'2018/11/30 13:24:29.440 INFO apply.rs:953: [region 27] [slow-query] 28 exec ConfChange "AddNode", epoch: conf_ver: 2 version: 12 ts: 404661852013068325',
                 r'2018/11/30 13:24:29.440 INFO apply.rs:953: [region 27] [slow-query] 28 exec ConfChange "AddNode", epoch: conf_ver: 2 version: 12 ts: 404661852013068325']
    tidb_text = '\n'.join(tidb_logs)
    tikv_text = '\n'.join(tikv_logs)
    # print(tikv_text)
    tidb_enties = parser.parse_text(tidb_text, entry.SOURCE_TIDB)
    tikv_enties = parser.parse_text(tikv_text, entry.SOURCE_TIKV)
    tidb = list(tidb_enties)
    tikv = list(tikv_enties)
    # print(tikv)
    print(slow_query_detect(tidb, tikv))
