"""
QuickUpdate
Hugo Zaragoza, 2020.

see README.md


"""
import argparse
from datetime import timedelta, datetime
import os
import pandas as pd
import re
import shutil

from utils import bold, myassert, date_string, debug, title_str, headline1, headline2

# ------------------------------------------------------------------------------------------------------------
# DESIGN
# ------------------------------------------------------------------------------------------------------------
app_name = "QuickUpdate"
version_name = "v 0.5"
err_pre = "INPUT DATA ERROR:"
design_bullet = "* "
DONE_POSFIX = ["(DONE)", "(.)"]
TODO_PREFIX = "#TODO "
TODO_CONT_PREFIX = "#- "

pd.set_option('display.max_columns', None)

# ------------------------------------------------------------------------------------------------------------
# MISC:
# ------------------------------------------------------------------------------------------------------------


date_rex = re.compile("^#\\s*(\\d+)[ /-](\\d+)[ /-](\\d+)\\n?$")


def parse_date(line):
    new_date = None
    date_m = re.search(date_rex, line)
    if date_m:
        new_date = datetime.strptime(
            "-".join([date_m.group(x) for x in range(1, 4)]), "%Y-%m-%d"
        ).date()
    return new_date


# ------------------------------------------------------------------------------------------------------------
# IO:
# ------------------------------------------------------------------------------------------------------------

# ------------
# INIT PARSER:

TASK_SEPARATOR = "::"  # TODO parametrise

# REGEX expressions:
regex_url = r"\b((?:https?://|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}/)(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s`!()\[\]{};:'\".,<>?«»“”‘’]))"
done_exp = "|".join([re.escape(x) for x in DONE_POSFIX])
done_exp = "(?P<done> " + done_exp + ")?"
line_parser_rex = re.compile(
    f"^(?P<task>[^][]+){TASK_SEPARATOR}[ \t]+(?P<update>.+?){done_exp}$"
)  # need on-greedy +? so update does not swallow DONE
# Task [Key] posfix # no update yet
alias_rex = re.compile(
    f"(?i)^\\[(?P<key>[^]]+)?\\][ \t]+(?P<task>.+){TASK_SEPARATOR}[ \t]*(?P<url>{regex_url})?[ \t]*(?:POSFIX:(?P<posfix>[^:]+):)?[ \t]*(?:ORDER:(?P<order>[^:]+):)?[ \t]*$"
)

url_shorthand_rex = re.compile(f"(?P<word>[^\\s]+):(?P<url>{regex_url})")

blank_rex = re.compile("^\\s*$")


def format_update(update):
    update = url_shorthand_rex.sub("[\\1](\\2)", update)

    if not re.match("[.!?]", update[-1]):
        update += "."
    update = f"{update[0].upper()}{update[1:]}"
    return update


def task_join(tasks):
    return " / ".join(tasks)


def task_split(tasks):
    return tasks.split(f"{TASK_SEPARATOR} ")


def parse_line(line, aliases, urls, posfixes, order):
    # PARSE
    alias = alias_rex.search(line)
    if alias:
        d = alias.groupdict()
        task = task_join(task_split(d["task"]))
        aliases[d["key"]] = task
        if "posfix" in d and d["posfix"]:
            posfixes[task] = d["posfix"]
        if "url" in d and d["url"]:
            urls[task] = d["url"]
        if "order" in d and d["order"]:
            order[task] = d["order"]
        return None
    elif line.startswith("["):  # bad alias line?
        raise SyntaxError(f"Could not parse task alias line: [{line}]")

    else:

        def _parse_task_line(line, aliases):
            rex = line_parser_rex.search(line)
            if not rex:
                raise SyntaxError
            d = rex.groupdict()
            tasklis = task_split(d["task"])
            tasklis[0] = aliases.get(tasklis[0], tasklis[0])
            task = task_join(tasklis)

            # try to math key form the left, longest first:
            task = aliases.get(task, task)
            done = True if d["done"] else False
            update = format_update(d["update"])
            return task, update, done

        task, update, done = _parse_task_line(line, aliases)
        # add posfix if needed:
        if task in posfixes:
            line = line + " " + posfixes[task]
            # mydebug(line)
            task, update, done = _parse_task_line(line, aliases)

        return task, update, done


def parse_file(string):
    date = None
    date_ascending = None
    linenum = 0
    data = []
    todos = []
    keys = {}
    urls = {}
    posfixes = {}
    order = {}

    lines = string.split("\n")
    for line in lines:
        line = line.strip()
        linenum += 1
        date_m = parse_date(line)
        if date_m:
            new_date = date_m
            if date:
                if not date_ascending:
                    date_ascending = new_date > date
                else:
                    if (date_ascending and new_date <= date) or (
                            not date_ascending and new_date >= date
                    ):
                        myassert(
                            new_date > date,
                            f"PARSE ERROR (LINE: {linenum}) Dates can be incremental or decremental but not both!",
                        )
            date = new_date
            continue
        elif line.startswith("#TODO"):
            todos.append(line)
            continue
        elif line.startswith("#- "):  # TODO continuation
            if todos[-1].startswith("#TODO"):
                todos[-1] += "\n" + line
            continue
        elif line.startswith("#") or blank_rex.match(line):
            continue

        try:
            res = parse_line(line, keys, urls, posfixes, order)
        except SyntaxError:
            myassert(False, f"PARSE ERROR (LINE: {linenum}):\n{line}")
        if res:
            task, update, done = res
            if update:
                myassert(
                    date,
                    f"PARSE ERROR (LINE: {linenum}) No date line present before the first update!",
                )

            data.append([date, task, update, done])

    df = pd.DataFrame(data, columns=["Date", "Task", "Update", "Done"])
    df.Date = pd.to_datetime(df.Date)

    # add Keys (for display):
    task_to_key = {v: k for k, v in keys.items()}
    all_keys = [
        task_to_key[task] if task in task_to_key else None for task in df.Task.tolist()
    ]
    all_order = [
        order[task] + task if task in order else task for task in df.Task.tolist()
    ]
    df["Key"] = all_keys
    df["Order"] = all_order

    return df, todos, posfixes, date_ascending


# ------------------------------------------------------------------------------------------------------------
# FILTERS:
# ------------------------------------------------------------------------------------------------------------


def start_dates(data):
    df = data
    df = df.sort_values(by=["Date"]).groupby(["Task"]).head(1)
    return df


def end_dates(data):
    return closed_tasks(data)


def open_tasks(data):
    df = data
    if _now:
        df = df[(df["Date"] <= _now)]
    df = df.sort_values(by=["Date"]).groupby(["Task"]).tail(1)
    df = df[(df["Done"] == False)]
    return df


def closed_tasks(data):
    df = data
    if _now:
        df = df[(df["Date"] <= _now)]
    df = df.sort_values(by=["Date"]).groupby(["Task"]).tail(1)
    df = df[(df["Done"])]
    return df


# ------------------------------------------------------------------------------------------------------------
# REPORT FORMATTING:
# ------------------------------------------------------------------------------------------------------------


def format_line(
        key,
        task,
        update="",
        done=False,
        date=None,
        level=0,
        display_key=True,
        display_done=False
):
    if display_key:
        key = f"[{key}]" if key else " "
        key = f"{key:7}"
    else:
        key = ""
    task = f"{task:30}\t" if task else ""
    ds = ''
    if date:
        ds = '(' + date_string(date) + ')'
        ds = f" {ds:s}"
    update = f": {update}" if update else ""
    prefx = "  " * (level + 1) + design_bullet
    task = f"{task}" if task else ""
    done = "" if not display_done else " (DONE)" if done else " (...)"
    l = f"{prefx}{key}{task}{update}{done}{ds}\n"

    return l


def report1(
        df,
        groupby,
        display_key=True,
        display_done=False,
        display_date=False,
        last_only=None,
        sortby="Date",
        ascending=False,
        display_group_headers=True
):
    ret = ""
    if last_only:
        df = df.sort_values("Date").groupby(last_only).tail(1)
    df = df.sort_values(sortby, ascending=ascending)
    df = df.groupby(groupby, sort=False)
    for name, group in df:
        tmp = ""
        nrows = 0
        for index, row in group.iterrows():
            tmp += format_line(
                row.Key,
                row.Task,
                row.Update,
                date=row.Date if display_date else None,
                done=row.Done,
                level=1,
                display_key=display_key,
                display_done=display_done,
            )
            nrows += 1

        if display_group_headers and nrows > 1:
            ret += design_bullet + str(name) + "\n" + tmp
        else:
            ret += tmp

    return ret




# ------------------------------------------------------------------------------------------------------------
# REPORTS:
# ------------------------------------------------------------------------------------------------------------


def report_tasks(df, posfix, title="TASKS DEFINED:"):
    #    df=df[df.Key.notnull()]
    df = df[["Task", "Key", "Order"]]
    df = df.drop_duplicates().sort_values("Order")
    ret = title_str(title) + "\n"
    for index, row in df.iterrows():
        k = f"[{row.Key}]" if row.Key else ""
        k = f"{k:10s}"
        posfix = f"POSFIX '{posfix[row.Task]}'" if row.Task in posfix else ""
        ret += f"{k}\t{row.Task}\t{posfix}\n"
    return ret


def report_open_tasks(df, title="OPEN TASKS:"):
    df = open_tasks(df)
    ret = title_str(title) + "\n"

    ret += report1(df, groupby="Task", display_date=True, display_key=False, last_only="Task", sortby="Order",
                   ascending=True)
    return ret


def report_log(df, task, title="LOG:"):
    tmp = df[df.Key==task]
    if len(tmp)>0:
        task=tmp.iloc[0].Task
    df = df[df.Task == task]
    ret = title_str(title) + "\n"
    ret += report1(df, groupby="Date", display_date=True, display_key=False, last_only=None, sortby="Date",
                   ascending=True, display_group_headers=False)
    return ret


def report_closed_tasks(df, title="CLOSED TASKS:"):
    df = closed_tasks(df)
    ret = title_str(title) + "\n"
    ret += report1(df, groupby="Task", display_date=False, display_key=False, last_only="Task", sortby="Order",
                   ascending=True)
    return ret


def report_last_week(df):
    date = _now
    startdate = date + timedelta(days=-date.weekday(), weeks=-1)
    enddate = startdate + timedelta(days=6)
    weekno = startdate.isocalendar()[1]
    datestr = f"{enddate.date().year} / {enddate.date().month} / {startdate.date().day}-{enddate.date().day}"

    ret = title_str(f"Last Week #{weekno}: {datestr}\n\n")
    ret += report_span(df, startdate, enddate)
    return ret


def report_this_week(df):
    date = _now
    startdate = date + timedelta(days=-date.weekday())
    enddate = startdate + timedelta(days=6)
    weekno = startdate.isocalendar()[1]
    datestr = f"{enddate.date().year} / {enddate.date().month} / {startdate.date().day}-{enddate.date().day}"

    ret = title_str(f"This Week #{weekno}: {datestr}\n\n")
    ret += report_span(df, startdate, enddate)
    return ret


def report_span(df, startdate, enddate):
    df = df[(df.Date >= str(startdate.date())) & (df.Date <= str(enddate.date()))]
    ret = ""
    df = df.groupby(["Order", "Task"])  # groupby order first to preserve right order
    SEP = " : "
    for (_, name), group in df:
        ret += design_bullet + name + SEP
        if group.shape[0] > 1:
            ret += "\n"
            for index, row in group.iterrows():
                ret += f"    {design_bullet}{row.Update}\n"
        else:
            row = [r for i, r in group.iterrows()]
            ret += row[0].Update + "\n"

    return ret


def report_last_days(df):
    ret = title_str("LAST TASKS") + "\n"
    for i in range(0, 3):
        date = _now
        date = date + timedelta(days=-i)
        dft = df[(df.Date == str(date.date()))]
        datestr = f"{date.date().year} / {date.date().month} / {date.date().day}"
        ret += f"Day {datestr}\n"
        ret += report1(
            dft, "Task", display_key=False, display_done=True, last_only=None
        )
    return ret


def show_day(df, offset, title_prefix=""):
    start_date = datetime.strftime(_now - timedelta(offset), "%Y-%m-%d")
    end_date = datetime.strftime(_now + timedelta(1), "%Y-%m-%d")
    title = f"{title_prefix}{start_date} - {end_date}:"

    mask = (df["Date"] >= start_date) & (df["Date"] <= end_date)
    df = df[mask]
    print(title_str(title))
    for index, row in df.iterrows():
        print(format_line(row.Key, row.Task, row.Update, row.Date))


# ------------------------------------------------------------------------------------------------------------
# FILE MANIPULATION
# ------------------------------------------------------------------------------------------------------------

def add_date_to_file(file, now):
    '''
    Rewrite file adding now's date entry.
    '''
    # Find out if ascending or descending:
    date_ascending = None
    date = None
    for line in open(file, "r"):
        d = re.search(date_rex, line)
        if d:
            d = datetime.strptime("-".join([d.group(x) for x in range(1, 4)]), "%Y-%m-%d")
            if date is None:
                date = d
            else:
                date_ascending = d > date
                break
    if date_ascending is None:
        return

    # Write new File:
    date_str = f"# {now.strftime('%Y-%m-%d')}\n\n\n"
    newfile = ""
    today_inserted = False
    for line in open(file, "r"):
        d = re.search(date_rex, line)
        if not today_inserted and d:
            d = datetime.strptime("-".join([d.group(x) for x in range(1, 4)]), "%Y-%m-%d").date()
            debug(f"1: {now.date()} - {d}")
            if d == now.date():
                today_inserted = True  # not needed
            else:
                if d and not date_ascending:
                    newfile += date_str
                    today_inserted = True
        newfile += line
    if not today_inserted:
        newfile += date_str
        today_inserted = True

    shutil.copyfile(file, f"{file}.old")

    with open(file, "w") as text_file:
        text_file.write(newfile)


# ------------------------------------------------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------------------------------------------------


def run_tests(df):
    #    print(df)
    #    print(report_tasks(df))
    print(df)
    # print(report_tasks(df))
    print(report_open_tasks(df))


#    print(report_closed_tasks(df))
#    print(show_done_tasks(df))
#    show_day(df, 1)

#   print("WEEKLY --------------")
#   print(report_last_week(df))


_now = datetime.now()


def main():
    help_msg = """
Commands: 
    help\t: this message
    tasks\t: list all tasks abbreviations
    todo\t: list todos    

    open\t: list last entry of each open tasks
    closed\t: list last entry of each closed task
    lastweek\t: list last entry for each task worked on last week
    thisweek\t: list last entry for each task worked on this week
    span <date1> <date2>\t: list last entry for each task worked on in this span

    log <task>\t: list all entried for this task, in chronological order
"""

    commands_list = ["log", "open", "closed", "lastweek", "span <date-start> <date-end>", "thisweek", "tasks", "todo"]

    ap = argparse.ArgumentParser(
        description="(https://github.com/hugozaragoza/quick-update/blob/main/README.md)")

    ap.add_argument(
        "commands",
        type=str,
        nargs="+",
        help= ", ".join(commands_list),
    )
    ap.add_argument(
        "-f",
        "--update_file",
        required=True,
        default=None,
        help="Update file",
    )
    ap.add_argument(
        "--now",
        required=False,
        help="Use a different date for today (for reports relative to today). Use format %%Y-%%m-%%d",
    )
    args = vars(ap.parse_args())

    if "help" in args["commands"]:
        ap.print_help()
        print(help_msg)
        return

    file = args["update_file"]

    print(
        bold(
            f"\n\n{headline1}\n{headline1}\n{headline1}\n{app_name} {version_name}\n{headline2}\n"
        )
    )
    print(f"UPDATE FILE: {file}")
    if (args['now']):
        global _now
        _now = datetime.strptime(args['now'], '%Y-%m-%d')
        print("WARNING: NOW is set to " + str(_now))

    print()

    if args["commands"] == ["all"]:
        args["commands"] = commands_list

    if "edit" in args["commands"]:
        add_date_to_file(file, _now)
        os.system(f"open {file}")
        args["commands"].remove("edit")

    if len(args["commands"]) == 0:
        return

    with open(file, "r") as _file:
        file_content = _file.read()
        df, todos, posfix, _ = parse_file(file_content)

    skip=0
    for i in range(len(args["commands"])):
        if skip>0:
            skip-=1
            continue;

        command = args["commands"][i]
        if command == "test":
            run_tests(df)

        elif command == "all":
            print(report_last_days(df))
            print(report_open_tasks(df))
            print(report_this_week(df))
            print(report_last_week(df))
            print(report_tasks(df, posfix))
            print(report_tasks(df))

        elif command == "log":
            task = args["commands"][i+1]
            skip+=1
            print(report_log(df, task))

        elif command == "thisweek":
            print(report_this_week(df))

        elif command == "span":
            startdate=datetime.strptime(args["commands"][i+1], '%Y-%m-%d')
            enddate=datetime.strptime(args["commands"][i+2], '%Y-%m-%d')
            print(title_str(f"SPAN: {startdate:%Y-%m-%d} - {enddate:%Y-%m-%d}\n\n"))
            print(report_span(df, startdate,enddate))
            skip+=2

        elif command == "open":
            print(report_open_tasks(df, title=bold("OPEN TASKS")))

        elif command == "closed":
            print(report_closed_tasks(df, bold("CLOSED TASKS")))

        elif command == "tasks":
            print(report_tasks(df, posfix))

        elif command == "todo":
            print(title_str("TODO"))
            print("\n".join(todos))

        elif command == "week":
            print(report_last_week(df))

        else:
            print(
                f"UNKNOWN COMMAND [{command}]. DEFINED COMMANDS: {', '.join(commands_list)}"
            )

    print(bold(f"\n{headline1}\n\n"))


if __name__ == "__main__":
    main()
