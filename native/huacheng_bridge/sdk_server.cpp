// Huacheng SDK V2.4.1 motion server for the ZYNQ board (ARM32 libxoip.so has no Python binding).
// One request line on stdin -> one reply line ("OK ..." / "ERR ...") on the protocol channel;
// motion-end callbacks arrive asynchronously as "EVT DONE <sequence> <end>".
// The protocol channel is the original stdout; the SDK's own console output is moved to stderr.
//
// Requests:
//   CONNECT <local_ip> <controller_ip> <port> <robot_id>   -> OK <lib_version> <host_version>
//   SPEED <0..100>                 setGlobalSpeed            -> OK <read back or -1>
//   GETSPEED                                                  -> OK <speed>
//   MOVEJ <smooth> <acc> <dec> <ratio> q1..qN   moveJoints   -> OK <sequence>
//   MOVEL <smooth> <acc> <dec> <ratio> x y z u v w  moveLine -> OK <sequence>
//   STATE                          move state / paused / link -> OK <move> <paused> <link>
//   JOINTS                         getJoints(feedback)        -> OK q1..qN
//   PAUSE <0|1>                    pauseRobot                 -> OK
//   STOP <0|1>                     clearRobotRoute(emergency) -> OK
//   ALARM                          isAlarming (read only, never clears) -> OK <count> [text|text]
//   QUIT                           stop_data and exit
// Never clears alarms, never changes protection, never enables servo, never streams PluseToServo.
#include "robot.h"
#include "xoip.h"
#include <cmath>
#include <cstdio>
#include <iostream>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unistd.h>
#include <vector>

using R = HCXSDKLib::RobotManager;
static FILE* proto = nullptr;
static std::mutex out_lock;
static int robot = 1;
static bool connected = false;

static void reply(const std::string& line) {
    std::lock_guard<std::mutex> guard(out_lock);
    std::fputs((line + "\n").c_str(), proto);
    std::fflush(proto);
}
static void require(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
static double number(std::istringstream& in, double lo, double hi, const char* what) {
    double v; require(static_cast<bool>(in >> v), what);
    require(std::isfinite(v) && v >= lo && v <= hi, what); return v;
}
static std::string clean(std::string s) {
    for (char& c : s) if (c == '\n' || c == '\r' || c == '|') c = ' ';
    return s;
}
static void on_end(int rid, bool end, uint64_t seq) {
    reply("EVT DONE " + std::to_string(seq) + " " + (end ? "1" : "0") + " " + std::to_string(rid));
}

static R::RobotActionParam motion(std::istringstream& in) {
    R::RobotActionParam p;
    p.smooth = int(number(in, 0, 9, "smooth must be 0..9"));
    double acc = number(in, 0, 1, "acc must be 0 or 0.1..1"), dec = number(in, 0, 1, "dec must be 0 or 0.1..1");
    require((acc == 0 || acc >= 0.1) && (dec == 0 || dec >= 0.1), "acc/dec must be 0 or 0.1..1");
    p.accTime = float(acc); p.decTime = float(dec);
    p.specifyGlobalSpeed = float(number(in, 0, 1, "ratio must be 0..1"));
    p.interrupt = false; p.needCallback = true; p.needBlock = false; p.delay_in_ms = 0;
    p.maxLineSpeed = 0; p.angularSpeed = 0; p.collabRobotID = 0; p.collabDirectionMask = 0;
    p.endJointIndex = 0; p.directIK = false;
    return p;
}

static std::string handle(const std::string& line) {
    std::istringstream in(line); std::string cmd; in >> cmd;
    if (cmd == "CONNECT") {
        require(!connected, "already connected");
        std::string local, remote; int port;
        require(static_cast<bool>(in >> local >> remote >> port >> robot), "CONNECT local remote port robot");
        require(port > 0 && port <= 65535 && robot > 0 && robot <= 32, "invalid port/robot id");
        connected = R::init_data(local, remote, uint32_t(port));
        if (!connected || !R::getLinkStatus()) { R::stop_data(); connected = false; throw std::runtime_error("SDK connection failed"); }
        require(R::registerMoveJointsEndCb(on_end) && R::registerMoveWorldsEndCb(on_end), "callback registration failed");
        return "OK " + clean(HCXSDKLib::VersionManager::getLibVersion()) + " " + clean(HCXSDKLib::VersionManager::getHostVersion());
    }
    if (cmd == "QUIT") return "OK";
    require(connected, "not connected");
    if (cmd == "SPEED") {
        double v = number(in, 0, 100, "speed must be 0..100");
        require(R::setGlobalSpeed(v), "setGlobalSpeed refused");
        return "OK " + std::to_string(R::getGlobalSpeed());
    }
    if (cmd == "GETSPEED") return "OK " + std::to_string(R::getGlobalSpeed());
    if (cmd == "MOVEJ" || cmd == "MOVEL") {
        R::RobotActionParam p = motion(in);
        std::vector<float> v; double x;
        while (in >> x) { require(std::isfinite(x) && std::fabs(x) <= 2000, "nonfinite or huge target"); v.push_back(float(x)); }
        uint64_t seq;
        if (cmd == "MOVEJ") {
            require(v.size() >= 6 && v.size() <= 7, "MOVEJ needs 6..7 joints");
            for (float q : v) require(std::fabs(q) <= 360, "joint beyond 360 deg");
            p.joints = v; seq = R::moveJoints(robot, p);
        } else {
            require(v.size() == 6, "MOVEL needs XYZUVW");
            p.endWorld = v; seq = R::moveLine(robot, p);
        }
        require(seq != 1, "SDK refused motion (sequence 1)");
        return "OK " + std::to_string(seq);
    }
    if (cmd == "STATE") {
        return "OK " + std::to_string(R::getRobotMoveState(robot)) + " " + (R::getRobotPaused(robot) ? "1" : "0") +
               " " + (R::getLinkStatus() ? "1" : "0");
    }
    if (cmd == "JOINTS") {
        std::vector<float> q; require(R::getJoints(robot, q, true) && !q.empty(), "joint feedback unavailable");
        std::string s = "OK"; for (float v : q) { require(std::isfinite(v), "nonfinite feedback"); s += " " + std::to_string(v); }
        return s;
    }
    if (cmd == "PAUSE") { int on = int(number(in, 0, 1, "PAUSE 0|1")); require(R::pauseRobot(robot, on == 1), "pauseRobot refused"); return "OK"; }
    if (cmd == "STOP") { int e = int(number(in, 0, 1, "STOP 0|1")); require(R::clearRobotRoute(robot, e == 1), "clearRobotRoute refused"); return "OK"; }
    if (cmd == "ALARM") {
        std::vector<std::string> a; bool on = R::isAlarming(a);
        std::string s = "OK " + std::to_string(on ? a.size() : 0);
        for (size_t i = 0; on && i < a.size(); ++i) s += (i ? "|" : " ") + clean(a[i]);
        return s;
    }
    throw std::runtime_error("unknown command");
}

int main() {
    int fd = dup(1);
    if (fd < 0 || dup2(2, 1) < 0 || !(proto = fdopen(fd, "w"))) return 3;
    std::string line; bool quit = false;
    while (!quit && std::getline(std::cin, line)) {
        if (line.empty()) continue;
        try {
            std::string r = handle(line); reply(r);
            quit = r == "OK" && line.rfind("QUIT", 0) == 0;
        } catch (const std::exception& e) {
            reply(std::string("ERR ") + clean(e.what()));
        }
    }
    if (connected) {
        // stdin closed without QUIT: the Python side died; stop any queued motion before leaving.
        if (!quit) { try { R::clearRobotRoute(robot, true); } catch (...) {} }
        try { R::stop_data(); } catch (...) {}
    }
    return 0;
}
