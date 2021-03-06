import os

from factclient.fact import Fact
import factclient.trace_pb2 as trace

from datetime import datetime

from factclient.provider.GenericFact import GenericFact

class AWSFact(GenericFact):

    def __init__(self, path="/proc/self/cgroup"):
        super().__init__()
        self.PATH = path

    # cost in euro/millisecond
    AWS_LAMBDA_COST = {128: 0.0000002083, 512: 0.0000008333, 1024: 0.0000016667, 1536: 0.0000025000, 2048: 0.0000033333,
                       3008: 0.0000048958}

    PATH = ""

    # selects closest mem config to estimate costs
    def get_closes(self, str_mb):
        mb = int(str_mb)
        if mb <= 128:
            return self.AWS_LAMBDA_COST[128]
        elif mb <= 512:
            return self.AWS_LAMBDA_COST[512]
        elif mb <= 1024:
            return self.AWS_LAMBDA_COST[1024]
        elif mb <= 2048:
            return self.AWS_LAMBDA_COST[2048]
        else:
            return self.AWS_LAMBDA_COST[3008]

    def collect(self, trace: trace.Trace, context):
        trace = super().collect(trace,context)

        if context is None:
            raise Exception

        # collect info from lambda context object
        trace.Memory = int(context.memory_limit_in_mb)
        trace.Tags["fname"] = context.function_name
        trace.Tags["fver"] = context.function_version
        trace.Tags["rid"] = context.aws_request_id
        trace.Logs[int(datetime.now().timestamp() * 1000)] = "RemainingTime {}".format(
            context.get_remaining_time_in_millis())
        if context.client_context is not None:
            if "inlcudeEnvironment" in Fact.config and Fact.config["inlcudeEnvironment"]:
                trace.Env.update(context.client_context.env)
                trace.Env.update(context.client_context.custom)

        # execution time estimate
        elat = (datetime.now().timestamp() * 1000 - Fact.start_time) // 100

        # cost estimate
        cost = elat * self.get_closes(context.memory_limit_in_mb)
        trace.Cost = cost

        return trace

    FREEZER_OFFSET = len("freezer:/sandbox-")

    def read_cgroup_ids(self, trace):
        file = open(self.PATH, 'r')
        lines = file.readlines()
        found = 0
        for line in lines:
            index = line.find("freezer")
            if index > 0:
                trace.Tags["freezer"] = line[index + self.FREEZER_OFFSET:].strip()
                found += 1
            index = line.find("sandbox-root-")
            if index > 0:
                line = line[index:]
                if len(line) < 57:
                    raise ValueError
                host = line[13:19]
                trace.Tags["host"] = host
                trace.HostID = host
                trace.Tags["service"] = line[36:42]
                trace.Tags["sandbox"] = line[51:57]
                found += 1
            if found >= 2:
                break

    def init(self, trace, context=None):
        trace = super().init(trace,context)
        log_name = os.environ.get("AWS_LAMBDA_LOG_STREAM_NAME")
        trace.Platform = 'AWS'
        trace.ContainerID = log_name
        trace.Region = os.environ.get("AWS_REGION")
        uptime = Fact.readFile("/proc/uptime").strip()
        trace.Tags["uptime"] = uptime

        try:
            self.read_cgroup_ids(trace)
        except Exception:
            trace.putTags("host", "U" + uptime)
            trace.setHostID("U" + uptime)
            trace.putTags("service", "undefined")
            trace.putTags("sandbox", "undefined")
            trace.putTags("freezer", "undefined")
        if context is not None:
            self.collect(trace, context)
        
        return trace
