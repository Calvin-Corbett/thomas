import faulthandler
from pathlib import Path

log_path = Path(r"C:\Users\corbe\Thomas\tmp_template_debug.log")
trace_path = Path(r"C:\Users\corbe\Thomas\tmp_template_debug.trace")


def log(msg):
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")
        fh.flush()


trace_file = trace_path.open("w", encoding="utf-8")
faulthandler.enable(file=trace_file)
faulthandler.dump_traceback_later(5, repeat=False, file=trace_file)

from thomas.template_engine import DictLoader, Environment

log("before env")
env = Environment(loader=DictLoader({"test": "{% if x is custom %}yes{% endif %}"}))
log("before add")


def custom_test(value: int) -> bool:
    return value > 10


env.add_test("custom", custom_test)
log("before get_template")
template = env.get_template("test")
log("after get_template")
result_true = template.render(x=15)
log("after render true:" + result_true)
result_false = template.render(x=5)
log("after render false:" + result_false)
