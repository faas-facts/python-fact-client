from datetime import datetime
from google.protobuf.timestamp_pb2 import Timestamp
from google.protobuf.duration_pb2 import Duration
from enum import Enum

from factclient.provider import AWSFact,GCFFact,ACFFact,OWFact,GenericFact
from factclient.trace_pb2 import Trace
import uuid
import os
import sys


class Provider(Enum):
    AWS = 0  # AWS Lambda
    ICF = 1  # IBM Cloud Functions
    GCF = 2  # Google Cloud Functions
    ACF = 3  # Azure Cloud Functions
    OWk = 4  # OpenWhisk
    Dok = 5  # Docker
    UND = 6  # UNDEFINED


class Fact:
    _ContainerID = uuid.uuid4()  # random generated container ID
    _RuntimeString = "{} {} Python {}".format(os.uname()[0], os.uname()[2], sys.version.split(' ')[0])
    config = {}
    _trace = Trace()
    _provider = None
    start_time = 0
    base = None

    # definition of function states
    PHASE = ["provisioned", "start", "update", "done"]

    @staticmethod
    def readFile(path):
        with open(path, 'r') as file:
            data = file.read()
        return data

    @staticmethod
    def fingerprint(trace, context):
        # selects provider based on env variables
        aws_key = os.getenv("AWS_LAMBDA_LOG_STREAM_NAME")
        gcf_key = os.getenv("X_GOOGLE_FUNCTION_NAME")
        ow_key = os.getenv("__OW_ACTION_NAME")
        acf_key = os.getenv("WEBSITE_HOSTNAME")

        if aws_key:
            Fact._provider =  AWSFact.AWSFact()
        elif gcf_key:
            Fact._provider = GCFFact.GCFFact()
        elif acf_key:
            Fact._provider = ACFFact.ACFFact()
        elif ow_key:
            # if os.path.isfile("/sys/hypervisor/uuid"):
            #     # TODO impelent ICF provider
            # else:
            #     # TODO impelent OWk provider
            #     #Provider.OWk
            Fact._provider = OWFact.OWFact()
        # default case provider unknown
        else:
            Fact._provider = GenericFact.GenericFact()
        
        assert(Fact._provider is not None)   

        Fact._provider.init(trace,context)  
        return

    @staticmethod
    def boot(configuration):

        Fact.config = configuration

        # create new trace
        trace = Trace()
        Fact._trace = trace

        trace.BootTime.CopyFrom(Fact.now())

        if "inlcudeEnvironment" in configuration and configuration["inlcudeEnvironment"]:
            trace.Env.update(os.environ)

        trace.ContainerID = str(Fact._ContainerID)
        trace.Runtime = Fact._RuntimeString
        trace.Timestamp.CopyFrom(Fact._trace.BootTime)

        if "lazy_loading" not in configuration or not configuration["lazy_loading"]:
            Fact.load(None)
            if "send_on_update" in configuration and configuration["send_on_update"]:
                Fact.send("provisioned")

        # set trace as base for easier trace generation
        Fact.base = trace

    @staticmethod
    def send(phase):
        # check if function phase is valid
        if phase not in Fact.PHASE:
            raise ValueError("{} is not a defined phase".format(phase))

        try:
            Fact.config["io"].send(phase, Fact._trace)
        except IOError as e:
            print("failed to send {}:{} - {}\n".format(phase, Fact._trace, e))

    @staticmethod
    def now():
        # timestamp shenanigans
        timestamp = Timestamp()
        timestamp.FromDatetime(datetime.now())
        return timestamp

    @staticmethod
    def load(context):
        # set provider and init trace
        Fact.fingerprint(Fact._trace, context)

        # connect to io module
        Fact.config["io"].connect(os.environ)

    @staticmethod
    def start(context, event):
        trace = Trace()
        trace.MergeFrom(Fact.base)
        trace.ID = str(uuid.uuid4())
        Fact._trace = trace
        Fact._trace.StartTime.CopyFrom(Fact.now())
        if Fact._provider is None:
            Fact.load(context)
        assert Fact._provider is not None

       
        Fact._provider.collect(Fact._trace, context)

        if "send_on_update" in Fact.config and Fact.config["send_on_update"]:
            Fact.send("start")

    @staticmethod
    def update(context, message, tags):

        assert Fact._provider is not None
        assert Fact.config["io"].connected
        key = int(datetime.now().timestamp() * 1000)
        Fact._trace.Logs[key] = message
        Fact._trace.Logs.update(tags)

        Fact._provider.collect(Fact._trace, context)

        if "send_on_update" in Fact.config and Fact.config["send_on_update"]:
            Fact.send("update")

    @staticmethod
    def done(context, message, args):
        assert Fact._provider is not None
        assert Fact.config["io"].connected

        Fact._trace.EndTime.CopyFrom(Fact.now())

        # convert timestamp to millis
        key = int(datetime.now().timestamp() * 1000)

        Fact._trace.Logs[key] = message
        Fact._trace.Args.extend(args)

        # duration of execution calculation and formatting
        duration = Duration()
        exec_time = Fact._trace.EndTime.seconds - Fact._trace.StartTime.seconds
        duration.FromSeconds(exec_time)
        Fact._trace.ExecutionLatency.CopyFrom(duration)

        Fact._provider.collect(Fact._trace, context)

        if "send_on_update" in Fact.config and Fact.config["send_on_update"]:
            Fact.send("done")

        return Fact._trace

    @staticmethod
    def set_parent_id(parent_id):
        # function to connect traces with each other using parent_id
        Fact._trace.ChildOf = parent_id
