import sys
from optparse import OptionParser

import gevent
from geventirc import Client
from geventirc import handlers
from geventirc.message import Command, Quit
from geventirc import replycode

class Whois(Command):
    """missing whois command from geventirc"""
    def __init__(self, nickname, server=None, prefix=None):
        # TODO: change to nicks and split with ','
        params = [nickname]
        if server is not None:
            params.insert(0, server)
        super(Whois, self).__init__(params, prefix=prefix)

class Enum(set):
    """simple enumeration for keeping state"""
    def __getattr__(self, name):
        if name in self:
            return name
        raise AttributeError

STATE = Enum(["READY", "WAITING_RESULTS", "QUITTING"])

class WhoisHandler(object):

    commands = ['001',
        replycode.RPL_WHOISUSER,
        replycode.RPL_WHOISCHANNELS,
        replycode.RPL_AWAY,
        replycode.RPL_WHOISIDLE,
        replycode.RPL_ENDOFWHOIS,
        replycode.RPL_WHOISCHANNELS,
        replycode.RPL_WHOISSERVER,
        replycode.RPL_WHOISOPERATOR,
        replycode.ERR_NOSUCHSERVER,
        replycode.ERR_NONICKNAMEGIVEN,
        replycode.ERR_NOSUCHNICK]

    def __init__(self, queue, verbose=False):
        self.queue = queue
        self.query = None
        self.result = list()
        self.state = STATE.READY
        self.verbose = verbose

    def __call__(self, client, msg):
        self.client = client
        if msg.command in [str(v) for v in (
                replycode.ERR_NOSUCHSERVER,
                replycode.ERR_NONICKNAMEGIVEN)]:
            self.result.append("Error processing nick {0}".format(self.query))

        elif msg.command in [str(v) for v in (
                replycode.RPL_WHOISUSER,
                replycode.RPL_WHOISCHANNELS,
                replycode.RPL_AWAY,
                replycode.RPL_WHOISIDLE,
                replycode.RPL_WHOISCHANNELS,
                replycode.RPL_WHOISSERVER,
                replycode.RPL_WHOISOPERATOR,
                replycode.ERR_NOSUCHNICK)]:
            self.processWhoisReply(msg.command, msg.params)

        elif msg.command == str(replycode.RPL_ENDOFWHOIS):
            # Query done, print the results and fetch more work
            self.doNextQuery()

        elif msg.command == '001' and self.state == STATE.READY:
            # we start asking when we are connected
            self.fetchWorkOrDie()
            self.state = STATE.WAITING_RESULTS
            client.send_message(Whois(self.query))
        return

    def doNextQuery(self):
            self.state = STATE.READY
            print "\n".join(self.result)
            self.result = list()
            self.fetchWorkOrDie()
            self.state = STATE.WAITING_RESULTS
            self.client.send_message(Whois(self.query))

    def fetchWorkOrDie(self):
        if self.state != STATE.READY:
            raise Error("invalid state for fetching more work")
        try:
            self.query = self.queue.get_nowait()
        except gevent.queue.Empty:
            self.state = STATE.QUITTING
            if self.client is not None:
                self.client.quit("all done, quitting")

    def processWhoisReply(self, command, params):
        if self.state != STATE.WAITING_RESULTS:
            raise Error("out-of-sync, not expecting response")
        
        if command == str(replycode.RPL_WHOISUSER):
            # "<nick> <user> <host> * :<real name>"
            nick = params[1]
            real_name = " ".join(params[params.index("*")+1:]) or "<none>"
            user_host = "@".join(params[2:4])
            self.result.append("Nick {0} is {1} connected from {2}".format(nick, real_name, user_host))
        elif command == str(replycode.RPL_WHOISSERVER):
            # "<nick> <server> :<server info>"
            nick = params[1]
            server = params[2]
            server_info = " ".join(params[3:])
            self.result.append("Nick {0} is connected on {1} ({2})".format(nick, server, server_info))
        elif command == str(replycode.RPL_WHOISCHANNELS):
            # "<nick> :*( ( "@" / "+" ) <channel> " " )"
            nick = params[1]
            channels = " ".join(params[2:])
            self.result.append("Nick {0} is on {1}".format(nick, channels))
        elif command == str(replycode.ERR_NOSUCHNICK):
            # Query done, print the results and fetch more work
            nick = params[1]
            message = " ".join(params[2:])
            if self.verbose:
                self.result.append("Nick {0} was not found: {1}".format(nick, message))
        else:
            print "UNKNOWN OUTPUT:", params
        return

def query_nicks(queries, server, verbose=False):
    queue = gevent.queue.Queue()
    for query in queries:
        queue.put(query)

    nick = 'geventircbot'
    irc = Client(server[0], nick, port=server[1])
    irc.add_handler(handlers.ping_handler, 'PING')
    if verbose:
        irc.add_handler(handlers.print_handler)
    irc.add_handler(WhoisHandler(queue, verbose))
    irc.start()
    irc.join()
    return

def read_servers(serversfile):
    servers = list()
    with open(serversfile) as f:
        servers = f.readlines()
    return [s.strip().split(':') for s in servers]

def parseCommandLine():
    usage = "usage: %prog [options] nick nick..."
    parser = OptionParser(usage=usage)
    parser.add_option("-s", "--servers", dest="serversfile", default="servers",
                      help="read irc servers from FILE", metavar="FILE")
    parser.add_option("-t", "--timeout", dest="timeout", default=300,
                      help="wait upto TIMEOUT seconds for the results",
                      metavar="TIMEOUT")
    parser.add_option("-v", "--verbose",
                      action="store_true", dest="verbose", default=False,
                      help="spew status messages to stdout")
    (options, args) = parser.parse_args()
    if len(args) < 1:
        parser.error("no nics to query")
    return (options, args)


def main():
    (options, args) = parseCommandLine()
    servers = read_servers(options.serversfile)

    jobs = [gevent.spawn(query_nicks, args, server, options.verbose) for server in servers]
    gevent.joinall(jobs, timeout=int(options.timeout))
    return 0


if __name__ == "__main__":
    sys.exit(main())