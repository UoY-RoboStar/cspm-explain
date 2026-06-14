// pybind11 wrapper for FDR's C++ API (Python 3)
//
// Build:
//   PYBIND11=$(python3 -c "import pybind11; print(pybind11.get_include())")
//   c++ -O2 -shared -fPIC -std=c++14 -D_GLIBCXX_USE_CXX11_ABI=0 \
//       -I/opt/fdr/include -I${PYBIND11} -I/usr/include/python3.11 \
//       fdr_api.cpp \
//       -L/opt/fdr/lib -Wl,-rpath=/usr/lib/x86_64-linux-gnu:/opt/fdr/lib -lfdr \
//       -o cspm_explain/fdr_ext.cpython-311-x86_64-linux-gnu.so

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <fdr/fdr.h>
#include <fdr/assertions/behaviour/min_acceptance_behaviour.h>

namespace py = pybind11;

using namespace FDR;
using namespace FDR::Assertions;
using namespace FDR::LTS;
using namespace FDR::Evaluator;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

static std::string machine_name_str(Session& session, const Machine& machine)
{
    auto name = session.machine_name(machine);
    return name ? name->to_string() : std::string("(anonymous)");
}

static std::string machine_name_from_behaviour(Session& session, const Behaviour& b)
{
    auto m = b.machine();
    if (!m) return "(anonymous)";
    return machine_name_str(session, *m);
}

// Return the node name at position step in b.node_path():
//   "__null__"    — node is null (bystander / not-yet-started)
//   "__unnamed__" — node exists but has no CSP name
//   otherwise     — the process name (e.g. "OFXrGAIUfL")
static std::string node_name_raw(Session& session, const Behaviour& b, int step)
{
    const auto& np = b.node_path();
    if (step < 0 || step >= static_cast<int>(np.size()))
        return "__unnamed__";
    const auto& node = np[static_cast<size_t>(step)];
    if (!node)
        return "__null__";
    auto m = b.machine();
    if (!m)
        return "__unnamed__";
    try {
        auto name = session.machine_node_name(*m, *node);
        return name ? name->to_string() : "__unnamed__";
    } catch (...) {
        return "__unnamed__";
    }
}

// Build a states list (length = trace_len + 1) using <unchanged>/<unnamed>
// sentinel strings that match what the CLI JSON produces.
static std::vector<std::string> build_states(Session& session, const Behaviour& b)
{
    const auto& np = b.node_path();
    std::vector<std::string> result;
    result.reserve(np.size());
    std::string prev_known;   // last actual name seen (not null / unnamed)

    for (size_t i = 0; i < np.size(); ++i) {
        std::string raw = node_name_raw(session, b, static_cast<int>(i));
        if (raw == "__null__") {
            result.push_back("<unchanged>");
        } else if (raw == "__unnamed__") {
            result.push_back("<unnamed>");
            prev_known.clear();
        } else if (raw == prev_known) {
            result.push_back("<unchanged>");
        } else {
            result.push_back(raw);
            prev_known = raw;
        }
    }
    return result;
}

// Return the min_acceptance of a MinAcceptanceBehaviour, or [] otherwise.
static std::vector<CompiledEvent> behaviour_min_acceptance(const Behaviour& b)
{
    const auto* mab = dynamic_cast<const MinAcceptanceBehaviour*>(&b);
    if (!mab) return {};
    return mab->min_acceptance();
}

// ---------------------------------------------------------------------------
// Module
// ---------------------------------------------------------------------------

PYBIND11_MODULE(fdr_ext, m)
{
    m.doc() = "Python 3 bindings for FDR's C++ libfdr API";

    // --- Library lifecycle ---------------------------------------------------

    m.def("library_init",     []() { FDR::library_init(); });
    m.def("library_exit",     &FDR::library_exit);
    m.def("has_valid_license",&FDR::has_valid_license);
    m.def("version",          &FDR::version);

    // --- Option --------------------------------------------------------------

    py::class_<Option, std::shared_ptr<Option>>(m, "Option")
        .def_static("get_option",  &Option::get_option)
        .def_static("options",     &Option::options)
        .def("name",           &Option::name)
        .def("description",    &Option::description)
        .def("get",            &Option::get)
        .def("set",            &Option::set)
        .def("default_value",  &Option::default_value)
        .def("allowed_values", &Option::allowed_values);

    // --- ProcessName / Event -------------------------------------------------

    py::class_<ProcessName, std::shared_ptr<ProcessName>>(m, "ProcessName")
        .def("to_string", &ProcessName::to_string);

    py::class_<Event, std::shared_ptr<Event>>(m, "Event")
        .def("to_string", &Event::to_string);

    // --- Machine (opaque handle) ---------------------------------------------

    py::class_<Machine, std::shared_ptr<Machine>>(m, "Machine");

    // --- Behaviour -----------------------------------------------------------

    py::class_<Behaviour, std::shared_ptr<Behaviour>>(m, "Behaviour")
        .def("machine",   &Behaviour::machine)
        .def("trace",     &Behaviour::trace)
        .def("node_path", &Behaviour::node_path)
        // min_acceptance: works for MinAcceptanceBehaviour children; [] otherwise.
        .def("min_acceptance",
             [](const Behaviour& self) {
                 return behaviour_min_acceptance(self);
             })
        // node_name_raw_at: raw sentinel string used by build_states in Python.
        .def("node_name_raw_at",
             [](const Behaviour& self, Session& sess, int step) -> std::string {
                 return node_name_raw(sess, self, step);
             },
             py::arg("session"), py::arg("step"))
        // states: full list of process-name strings, length = trace_len + 1.
        .def("states",
             [](const Behaviour& self, Session& sess) {
                 return build_states(sess, self);
             },
             py::arg("session"),
             "Return the state-name list (length trace_len+1). Uses <unchanged>/<unnamed> sentinels.");

    // --- Session -------------------------------------------------------------

    py::class_<Session>(m, "Session")
        .def(py::init<>())
        .def("load_file", &Session::load_file)
        .def("assertions", &Session::assertions)
        .def("machine_name",
             [](Session& self, const std::shared_ptr<Machine>& m) -> std::string {
                 if (!m) return "(null)";
                 auto name = self.machine_name(*m);
                 return name ? name->to_string() : "(anonymous)";
             })
        .def("machine_name_from_behaviour",
             [](Session& self, const std::shared_ptr<Behaviour>& b) -> std::string {
                 if (!b) return "(null)";
                 return machine_name_from_behaviour(self, *b);
             })
        .def("uncompile_event",
             [](Session& self, CompiledEvent ev) -> std::string {
                 try {
                     auto ep = self.uncompile_event(ev);
                     return ep ? ep->to_string() : "";
                 } catch (...) { return ""; }
             })
        .def("uncompile_events",
             [](Session& self, const std::vector<CompiledEvent>& evs) -> std::vector<std::string> {
                 std::vector<std::string> out;
                 out.reserve(evs.size());
                 for (auto ev : evs) {
                     try {
                         auto ep = self.uncompile_event(ev);
                         out.push_back(ep ? ep->to_string() : "");
                     } catch (...) { out.push_back(""); }
                 }
                 return out;
             });

    // --- Counterexample hierarchy --------------------------------------------

    py::class_<Counterexample, std::shared_ptr<Counterexample>>(m, "Counterexample");

    py::class_<PropertyCounterexample, Counterexample,
               std::shared_ptr<PropertyCounterexample>>(m, "PropertyCounterexample")
        .def("behaviour", &PropertyCounterexample::behaviour);

    py::class_<DeadlockCounterexample, PropertyCounterexample,
               std::shared_ptr<DeadlockCounterexample>>(m, "DeadlockCounterexample");

    // --- Assertion -----------------------------------------------------------

    py::class_<Assertion, std::shared_ptr<Assertion>>(m, "Assertion")
        .def("execute",           [](Assertion& self) { self.execute(nullptr); })
        .def("passed",            &Assertion::passed)
        .def("to_string",         &Assertion::to_string)
        .def("counterexamples",   &Assertion::counterexamples)
        .def("counterexample_as_deadlock",
             [](Assertion& self, size_t idx) -> std::shared_ptr<DeadlockCounterexample> {
                 const auto& ces = self.counterexamples();
                 if (idx >= ces.size()) return nullptr;
                 return std::dynamic_pointer_cast<DeadlockCounterexample>(ces[idx]);
             });

    // --- DebugContext --------------------------------------------------------

    py::class_<DebugContext>(m, "DebugContext")
        .def(py::init([](const std::shared_ptr<Counterexample>& ce, bool elide) {
                 auto* pce = dynamic_cast<PropertyCounterexample*>(ce.get());
                 if (!pce) throw std::invalid_argument("Expected a PropertyCounterexample");
                 return new DebugContext(*pce, elide);
             }),
             py::arg("counterexample"), py::arg("elide_uninteresting") = true)
        .def("initialise",
             [](DebugContext& self) { self.initialise(nullptr); })
        .def("root_behaviours",  &DebugContext::root_behaviours)
        .def("behaviour_children",&DebugContext::behaviour_children)
        .def("full_alphabet",    &DebugContext::full_alphabet,
             "Union of alphabets of all machines in this debug tree.")
        .def("reveal_tau",
             [](DebugContext& self,
                const std::shared_ptr<Behaviour>& b,
                unsigned int idx) -> py::object {
                 if (!b) return py::none();
                 auto r = self.reveal_tau(*b, idx);
                 return r ? py::cast(r) : py::none();
             },
             py::arg("behaviour"), py::arg("index"))
        .def("reveal_taus_in_trace",
             [](DebugContext& self, const std::shared_ptr<Behaviour>& b) {
                 if (!b) return std::vector<CompiledEvent>{};
                 return self.reveal_taus_in_trace(*b);
             });

    // --- Constants -----------------------------------------------------------

    m.attr("INVALID_EVENT") = py::int_((unsigned int)LTS::INVALID_EVENT);
    m.attr("TAU")           = py::int_((unsigned int)LTS::TAU);
}
