// C bridge around FDR's C++ API so it can be called from Python via ctypes.
//
// All FDR C++ objects are heap-boxed as shared_ptr held in opaque handles.
// The caller is responsible for calling the corresponding _free() on each
// handle it receives.
//
// Build:
//   c++ -O2 -shared -fPIC -std=c++14 \
//       -I/opt/fdr/include \
//       fdr_bridge.cpp \
//       -L/opt/fdr/lib -Wl,-rpath=/opt/fdr/lib -lfdr \
//       -o fdr_bridge.so

#include <cstring>
#include <memory>
#include <string>
#include <vector>

#include <fdr/fdr.h>

using namespace FDR;
using namespace FDR::Assertions;
using namespace FDR::LTS;
using namespace FDR::Evaluator;

// ---------------------------------------------------------------------------
// Opaque handle boxes (heap-allocated shared_ptr wrappers)
// ---------------------------------------------------------------------------

struct SessionBox    { std::unique_ptr<Session> ptr; };
struct AssertionBox  { std::shared_ptr<Assertion> ptr; };
struct CeBox         { std::shared_ptr<Counterexample> ptr; };
struct BehaviourBox  { std::shared_ptr<Behaviour> ptr; };
struct DbgCtxBox     { std::unique_ptr<DebugContext> ptr; };

// ---------------------------------------------------------------------------
// String helper: write into caller-supplied buffer, always NUL-terminate.
// ---------------------------------------------------------------------------

static void str_to_buf(const std::string& s, char* buf, size_t sz)
{
    if (!buf || sz == 0) return;
    size_t n = std::min(s.size(), sz - 1);
    std::memcpy(buf, s.data(), n);
    buf[n] = '\0';
}

// ---------------------------------------------------------------------------
// Exported C API
// ---------------------------------------------------------------------------

extern "C"
{

// --- Library lifecycle ------------------------------------------------------

void fdr_library_init(void)
{
    FDR::library_init();
}

void fdr_library_exit(void)
{
    FDR::library_exit();
}

int fdr_has_valid_license(void)
{
    return FDR::has_valid_license() ? 1 : 0;
}

void fdr_version(char* buf, size_t sz)
{
    str_to_buf(FDR::version(), buf, sz);
}

// --- Options ----------------------------------------------------------------

void fdr_set_option(const char* name, const char* value)
{
    try {
        Option::get_option(std::string(name))->set(std::string(value));
    } catch (...) {}
}

void fdr_get_option(const char* name, char* buf, size_t sz)
{
    try {
        str_to_buf(Option::get_option(std::string(name))->get(), buf, sz);
    } catch (...) {
        if (buf && sz) buf[0] = '\0';
    }
}

// --- Session ----------------------------------------------------------------

void* fdr_session_new(void)
{
    auto* box = new SessionBox();
    box->ptr = std::make_unique<Session>();
    return box;
}

void fdr_session_free(void* handle)
{
    delete static_cast<SessionBox*>(handle);
}

// Returns 0 on success, -1 on error (with message written to error_buf).
int fdr_session_load_file(void* handle, const char* path, char* error_buf, size_t error_buf_sz)
{
    auto* box = static_cast<SessionBox*>(handle);
    try {
        box->ptr->load_file(std::string(path));
        return 0;
    } catch (const std::exception& e) {
        str_to_buf(e.what(), error_buf, error_buf_sz);
        return -1;
    }
}

int fdr_session_assertion_count(void* handle)
{
    auto* box = static_cast<SessionBox*>(handle);
    return static_cast<int>(box->ptr->assertions().size());
}

// Returns a new AssertionBox* (caller must fdr_assertion_free it).
void* fdr_session_assertion(void* handle, int idx)
{
    auto* box = static_cast<SessionBox*>(handle);
    const auto& v = box->ptr->assertions();
    if (idx < 0 || idx >= static_cast<int>(v.size())) return nullptr;
    auto* ab = new AssertionBox();
    ab->ptr = v[static_cast<size_t>(idx)];
    return ab;
}

void fdr_session_uncompile_event(void* handle, unsigned int event, char* buf, size_t sz)
{
    auto* box = static_cast<SessionBox*>(handle);
    try {
        auto ev = box->ptr->uncompile_event(static_cast<CompiledEvent>(event));
        if (ev) str_to_buf(ev->to_string(), buf, sz);
        else    str_to_buf("(tau)", buf, sz);
    } catch (...) {
        str_to_buf("(error)", buf, sz);
    }
}

// Return machine name of the behaviour's machine, via Session::machine_name().
void fdr_session_machine_name_for_behaviour(void* session_handle, void* beh_handle, char* buf, size_t sz)
{
    auto* sbox = static_cast<SessionBox*>(session_handle);
    auto* bbox = static_cast<BehaviourBox*>(beh_handle);
    if (!sbox || !bbox || !bbox->ptr) { str_to_buf("(null)", buf, sz); return; }
    auto m = bbox->ptr->machine();
    if (!m) { str_to_buf("(anonymous)", buf, sz); return; }
    try {
        auto name = sbox->ptr->machine_name(*m);
        str_to_buf(name ? name->to_string() : "(anonymous)", buf, sz);
    } catch (...) {
        str_to_buf("(error)", buf, sz);
    }
}

// --- Assertion --------------------------------------------------------------

void fdr_assertion_free(void* handle)
{
    delete static_cast<AssertionBox*>(handle);
}

// Returns 0 on success, -1 on error.
int fdr_assertion_execute(void* handle, char* error_buf, size_t error_buf_sz)
{
    auto* box = static_cast<AssertionBox*>(handle);
    try {
        box->ptr->execute(nullptr);
        return 0;
    } catch (const std::exception& e) {
        str_to_buf(e.what(), error_buf, error_buf_sz);
        return -1;
    }
}

int fdr_assertion_passed(void* handle)
{
    auto* box = static_cast<AssertionBox*>(handle);
    return box->ptr->passed() ? 1 : 0;
}

void fdr_assertion_to_string(void* handle, char* buf, size_t sz)
{
    auto* box = static_cast<AssertionBox*>(handle);
    str_to_buf(box->ptr->to_string(), buf, sz);
}

int fdr_assertion_counterexample_count(void* handle)
{
    auto* box = static_cast<AssertionBox*>(handle);
    return static_cast<int>(box->ptr->counterexamples().size());
}

// Returns a new CeBox* (caller must fdr_ce_free it).
void* fdr_assertion_counterexample(void* handle, int idx)
{
    auto* box = static_cast<AssertionBox*>(handle);
    const auto& v = box->ptr->counterexamples();
    if (idx < 0 || idx >= static_cast<int>(v.size())) return nullptr;
    auto* cb = new CeBox();
    cb->ptr = v[static_cast<size_t>(idx)];
    return cb;
}

// --- Counterexample ---------------------------------------------------------

void fdr_ce_free(void* handle)
{
    delete static_cast<CeBox*>(handle);
}

// Returns 1 if the counterexample is a PropertyCounterexample (deadlock/div),
// 0 otherwise.
int fdr_ce_is_property(void* handle)
{
    auto* box = static_cast<CeBox*>(handle);
    return dynamic_cast<PropertyCounterexample*>(box->ptr.get()) ? 1 : 0;
}

// Returns a BehaviourBox* for the property counterexample behaviour.
void* fdr_ce_property_behaviour(void* handle)
{
    auto* box = static_cast<CeBox*>(handle);
    auto* pce = dynamic_cast<PropertyCounterexample*>(box->ptr.get());
    if (!pce) return nullptr;
    auto* bb = new BehaviourBox();
    bb->ptr = pce->behaviour();
    return bb;
}

// --- Behaviour --------------------------------------------------------------

void fdr_behaviour_free(void* handle)
{
    delete static_cast<BehaviourBox*>(handle);
}

int fdr_behaviour_trace_len(void* handle)
{
    auto* box = static_cast<BehaviourBox*>(handle);
    return static_cast<int>(box->ptr->trace().size());
}

unsigned int fdr_behaviour_trace_event(void* handle, int idx)
{
    auto* box = static_cast<BehaviourBox*>(handle);
    return box->ptr->trace()[static_cast<size_t>(idx)];
}

// --- DebugContext -----------------------------------------------------------

// Creates a DebugContext from a counterexample. Only works for
// PropertyCounterexample (deadlock etc.).
// Returns nullptr if the CE is not a property CE.
void* fdr_debug_context_new(void* ce_handle, int elide_uninteresting)
{
    auto* box = static_cast<CeBox*>(ce_handle);
    auto* pce = dynamic_cast<PropertyCounterexample*>(box->ptr.get());
    if (!pce) return nullptr;
    auto* db = new DbgCtxBox();
    try {
        db->ptr = std::make_unique<DebugContext>(*pce, elide_uninteresting != 0);
    } catch (...) {
        delete db;
        return nullptr;
    }
    return db;
}

void fdr_debug_context_free(void* handle)
{
    delete static_cast<DbgCtxBox*>(handle);
}

int fdr_debug_context_initialise(void* handle, char* error_buf, size_t error_buf_sz)
{
    auto* box = static_cast<DbgCtxBox*>(handle);
    try {
        box->ptr->initialise(nullptr);
        return 0;
    } catch (const std::exception& e) {
        str_to_buf(e.what(), error_buf, error_buf_sz);
        return -1;
    }
}

int fdr_debug_context_root_behaviour_count(void* handle)
{
    auto* box = static_cast<DbgCtxBox*>(handle);
    return static_cast<int>(box->ptr->root_behaviours().size());
}

// Returns a BehaviourBox* (caller must fdr_behaviour_free it).
void* fdr_debug_context_root_behaviour(void* handle, int idx)
{
    auto* box = static_cast<DbgCtxBox*>(handle);
    const auto& v = box->ptr->root_behaviours();
    if (idx < 0 || idx >= static_cast<int>(v.size())) return nullptr;
    auto* bb = new BehaviourBox();
    bb->ptr = v[static_cast<size_t>(idx)];
    return bb;
}

int fdr_debug_context_children_count(void* ctx_handle, void* beh_handle)
{
    auto* ctx = static_cast<DbgCtxBox*>(ctx_handle);
    auto* beh = static_cast<BehaviourBox*>(beh_handle);
    return static_cast<int>(ctx->ptr->behaviour_children(*beh->ptr).size());
}

// Returns a BehaviourBox* (caller must fdr_behaviour_free it).
void* fdr_debug_context_child(void* ctx_handle, void* beh_handle, int idx)
{
    auto* ctx = static_cast<DbgCtxBox*>(ctx_handle);
    auto* beh = static_cast<BehaviourBox*>(beh_handle);
    const auto& v = ctx->ptr->behaviour_children(*beh->ptr);
    if (idx < 0 || idx >= static_cast<int>(v.size())) return nullptr;
    auto* bb = new BehaviourBox();
    bb->ptr = v[static_cast<size_t>(idx)];
    return bb;
}

// Reveal which child behaviour performs the hidden event at trace position
// *index*. Returns nullptr if tau is from non-determinism (no source).
void* fdr_debug_context_reveal_tau(void* ctx_handle, void* beh_handle, unsigned int index)
{
    auto* ctx = static_cast<DbgCtxBox*>(ctx_handle);
    auto* beh = static_cast<BehaviourBox*>(beh_handle);
    try {
        auto result = ctx->ptr->reveal_tau(*beh->ptr, index);
        if (!result) return nullptr;
        auto* bb = new BehaviourBox();
        bb->ptr = result;
        return bb;
    } catch (...) {
        return nullptr;
    }
}

// Returns heap-allocated array of compiled events (with tau replaced by
// actual hidden events). *count_out receives the array length.
// Caller must call fdr_free_events() on the returned pointer.
unsigned int* fdr_debug_context_reveal_taus_in_trace(void* ctx_handle, void* beh_handle, int* count_out)
{
    auto* ctx = static_cast<DbgCtxBox*>(ctx_handle);
    auto* beh = static_cast<BehaviourBox*>(beh_handle);
    try {
        auto v = ctx->ptr->reveal_taus_in_trace(*beh->ptr);
        *count_out = static_cast<int>(v.size());
        auto* arr = new unsigned int[v.size()];
        for (size_t i = 0; i < v.size(); ++i) arr[i] = v[i];
        return arr;
    } catch (...) {
        *count_out = 0;
        return nullptr;
    }
}

void fdr_free_events(unsigned int* arr)
{
    delete[] arr;
}

} // extern "C"
