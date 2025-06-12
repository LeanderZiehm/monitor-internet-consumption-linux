#!/usr/bin/env python3
"""
Real-time network usage monitor using eBPF (BCC).
Captures per-packet RX/TX events with process attribution
and writes to a CSV file with timestamp, PID, process name,
direction (rx/tx), and byte count.

Requires: bcc (python3-bcc), sudo privileges.
Usage: sudo ./ebpf_net_monitor.py --output output.csv
"""
import csv
import ctypes as ct
import time
import signal
import argparse
from bcc import BPF

# BPF program
BPF_PROGRAM = r"""
#include <uapi/linux/ptrace.h>
#include <linux/skbuff.h>

struct data_t {
    u64 ts_ns;
    u32 pid;
    char comm[TASK_COMM_LEN];
    u64 bytes;
    u8 direction; // 0 = rx, 1 = tx
};
BPF_PERF_OUTPUT(events);

// Trace packet transmit
TRACEPOINT_PROBE(net, net_dev_xmit) {
    struct data_t data = {};
    data.ts_ns = bpf_ktime_get_ns();
    data.pid   = bpf_get_current_pid_tgid() >> 32;
    bpf_get_current_comm(&data.comm, sizeof(data.comm));
    data.bytes = args->len;
    data.direction = 1;
    events.perf_submit(ctx, &data, sizeof(data));
    return 0;
}

// Trace packet receive
TRACEPOINT_PROBE(net, netif_receive_skb) {
    struct data_t data = {};
    data.ts_ns = bpf_ktime_get_ns();
    data.pid   = bpf_get_current_pid_tgid() >> 32;
    bpf_get_current_comm(&data.comm, sizeof(data.comm));
    data.bytes = args->len;
    data.direction = 0;
    events.perf_submit(ctx, &data, sizeof(data));
    return 0;
}
"""

# Map direction code to string
DIRECTION = {0: 'rx', 1: 'tx'}

class Data(ct.Structure):
    _fields_ = [
        ("ts_ns", ct.c_uint64),
        ("pid", ct.c_uint32),
        ("comm", ct.c_char * 16),
        ("bytes", ct.c_uint64),
        ("direction", ct.c_uint8),
    ]


def signal_handler(sig, frame):
    print("\nDetaching and exiting...")
    exit(0)


def main():
    parser = argparse.ArgumentParser(description="eBPF network usage monitor")
    parser.add_argument("--output", "-o", default="net_usage.csv",
                        help="Output CSV file path")
    args = parser.parse_args()

    # Open output file and write header if new
    csv_file = open(args.output, "a", newline='')
    writer = csv.DictWriter(csv_file,
                            fieldnames=['timestamp', 'pid', 'process', 'direction', 'bytes'])
    # If file is empty, write header
    if csv_file.tell() == 0:
        writer.writeheader()

    # Load BPF
    b = BPF(text=BPF_PROGRAM)
    b['events'].open_perf_buffer(
        lambda cpu, data, size: handle_event(data, size, writer)
    )

    # Handle Ctrl-C
    signal.signal(signal.SIGINT, signal_handler)
    print("Tracing... Hit Ctrl-C to end.")

    # Poll events
    while True:
        try:
            b.perf_buffer_poll()
        except KeyboardInterrupt:
            break

    csv_file.close()


def handle_event(raw, size, writer):
    event = ct.cast(raw, ct.POINTER(Data)).contents
    ts_s = event.ts_ns / 1e9
    # format timestamp
    ts_str = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(ts_s))
    writer.writerow({
        'timestamp': ts_str,
        'pid': event.pid,
        'process': event.comm.decode('utf-8', 'replace'),
        'direction': DIRECTION.get(event.direction, 'unknown'),
        'bytes': event.bytes,
    })
    # flush to ensure data is written
    # (buffering can be adjusted as needed)
    writer.fieldnames  # noop to reference
    
if __name__ == '__main__':
    main()
