"""CSP-M parser — translated from robostar.CSPM Xtext grammar (UoY-RoboStar/cspm-textual).

Uses lark's Earley parser with dynamic lexer and propagate_positions so every
Tree node carries (line, column) metadata from the source file.
"""
from __future__ import annotations

from lark import Lark, Tree, Token  # noqa: F401 (re-exported for callers)

# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------
# Translation notes:
#   • Xtext "hidden(WS, NEWLINE, …)" → %ignore everywhere (all whitespace ignored)
#   • Xtext assignments (=, +=, ?=) → dropped; lark builds the tree automatically
#   • Xtext {TypeName} action annotations → replaced by -> alias on alternatives
#   • Xtext "returns X" type-return clauses → dropped
#   • Xtext "fragment" rules → translated to regular rules (transparent where safe)
#   • Xtext cross-references [Module|QualifiedName] → simplified to qualified_name
#   • EGA [| ambiguity (Exception vs GeneralisedParallel) → Earley resolves it
#     naturally since the two branches end with different tokens (|> vs |])
# ---------------------------------------------------------------------------

GRAMMAR = r"""
// ── Ignored tokens ────────────────────────────────────────────────────────────
%ignore /[ \t\r\n]+/
%ignore /\{-(?s:.*?)-\}/
%ignore /--[^\r\n]*/

// ── Terminals ─────────────────────────────────────────────────────────────────
// ID allows trailing primes, e.g.  x'  or  f''
ID    : /[a-zA-Z][a-zA-Z_0-9]*'*/
INT   : /[0-9]+/
STRING: /"(?:\\.|[^"\\])*"/
CHAR  : /'(?:\\.|[^'\\])'/

// ── VALIDID: plain ID or contextual keywords usable as identifiers ─────────────
// (F, T, FD, has, free, deadlock, deterministic, divergence per the Xtext grammar)
validid: ID
       | "F" | "T" | "FD"
       | "has" | "free" | "deadlock" | "deterministic" | "divergence"

qualified_name: validid ("::" validid)*

// ── Top-level ─────────────────────────────────────────────────────────────────
cspm: definition*

?definition: include_def
           | assertion
           | channel_list
           | data_type
           | sub_type
           | name_type
           | print_stmt
           | external_def
           | transparent_def
           | function_def
           | timed_section
           | module_def
           | module_instance
           | type_annotation

include_def    : "include" STRING
external_def   : "external" validid ("," validid)*
transparent_def: "transparent" validid ("," validid)*

// ── Assertions ────────────────────────────────────────────────────────────────
assertion: "assert" assertion_body

?assertion_body: refinement_assertion
               | deadlock_assertion
               | divergence_assertion
               | determinism_assertion
               | has_trace_assertion

refinement_assertion : "not"? expression "[" semantic_model "=" expression
deadlock_assertion   : "not"? expression ":[" "deadlock" "-"? "free" ("[" semantic_model "]")? "]"
divergence_assertion : "not"? expression ":[" "divergence" "-"? "free" ("[" semantic_model "]")? "]"
determinism_assertion: "not"? expression ":[" "deterministic" ("[" semantic_model "]")? "]"
has_trace_assertion  : "not"? expression ":[" "has" "trace" "]:" expression

semantic_model: "T" | "F" | "FD"

// ── Timed section ─────────────────────────────────────────────────────────────
timed_section: "Timed" "(" expression ")" "{" definition* "}"

// ── Type and channel declarations ─────────────────────────────────────────────
channel_list: "channel" channel ("," channel)* (":" expression)?
channel     : validid

data_type  : "datatype" validid "=" constructor ("|" constructor)*
sub_type   : "subtype"  validid "=" constructor ("|" constructor)*
name_type  : "nametype" validid "=" expression
constructor: validid ("." expression)?

// ── Modules ───────────────────────────────────────────────────────────────────
module_def     : "module" validid ("(" pattern ("," pattern)* ")")? definition* "exports" definition* "endmodule"
module_instance: "instance" validid "=" qualified_name ("(" expression ("," expression)* ")")?

// ── Print ─────────────────────────────────────────────────────────────────────
print_stmt: "print" expression

// ── Function / constant definition ───────────────────────────────────────────
// Either   name = expr        (constant)
// or       name(p1,p2,...) = expr  (function with pattern-matched args)
function_def: validid ("(" pattern ("," pattern)* ")")? "=" expression

// ── Patterns ─────────────────────────────────────────────────────────────────
pattern: dot_pat

dot_pat    : concat_pat "." concat_pat -> dot_pat
           | concat_pat

concat_pat : basic_pat "^" basic_pat ("^" basic_pat)* -> concat_pat
           | basic_pat

?basic_pat: variable_pat
          | wildcard_pat
          | list_pat
          | literal_pat
          | paren_pat
          | set_pat
          | tuple_pat

wildcard_pat: "_"
variable_pat: validid
list_pat    : "<" (pattern ("," pattern)*)? ">"
literal_pat : INT    -> int_pat
            | STRING -> string_pat
            | CHAR   -> char_pat
paren_pat   : "(" pattern ")"
set_pat     : "{" pattern? "}"
tuple_pat   : "(" pattern "," pattern ("," pattern)* ")"

// ── Expressions ───────────────────────────────────────────────────────────────
// Top of the expression hierarchy: LetExp | ReplicatedOps | DoublePatternExp
expression: let_exp
          | replicated_ops
          | double_pat_exp

let_exp: "let" definition+ "within" expression

// Replicated operators (prefix forms)
?replicated_ops: "||"  statement ("," statement)* "@" "[" expression "]" expression -> repl_alpha_par
               | "[]"  statement ("," statement)* "@" expression                    -> repl_ext_choice
               | "[|"  expression "|]" statement ("," statement)* "@" expression   -> repl_gen_par
               | "|||" statement ("," statement)* "@" expression                    -> repl_interleave
               | "|~|" statement ("," statement)* "@" expression                    -> repl_int_choice
               | "["   link ("," link)* ("|" statement ("," statement)*)? "]" statement ("," statement)* "@" expression -> repl_linked_par
               | ";"   statement ("," statement)* "@" expression                    -> repl_seq_comp
               | "[+"  expression "+]" "@" expression                               -> repl_sync_par

link: expression "<->" expression

// ── Precedence tower (lowest → highest binding) ───────────────────────────────
// Each level is transparent (?rule) so it is inlined when there is a single child.

?double_pat_exp: hide_exp "@@" hide_exp -> double_pat_exp
               | hide_exp

?hide_exp: hide_exp "\\" interleave_exp -> hide_exp
         | interleave_exp

?interleave_exp: interleave_exp "|||" ega_exp -> interleave_exp
               | ega_exp

// EGA: generalised parallel / exception / alphabetised parallel / linked parallel.
// The [|…|> (exception) vs [|…|] (gen-par) ambiguity is handled naturally by
// Earley since the two branches end with different closing tokens.
?ega_exp: ega_exp "[|" expression "|>" int_choice_exp   -> exception_exp
        | ega_exp "[|" expression "|]" int_choice_exp   -> gen_par_exp
        | ega_exp "[" expression "||" expression "]" int_choice_exp -> alpha_par_exp
        | ega_exp "[" link ("|" statement ("," statement)*)? "]" int_choice_exp -> linked_par_exp
        | int_choice_exp

?int_choice_exp: int_choice_exp "|~|" ext_choice_exp -> int_choice_exp
               | ext_choice_exp

?ext_choice_exp: ext_choice_exp "[]" interrupt_exp               -> ext_choice_exp
               | ext_choice_exp "[+" expression "+]" interrupt_exp -> sync_ext_choice_exp
               | interrupt_exp

?interrupt_exp: interrupt_exp "/\\" slide_exp                       -> interrupt_exp
              | interrupt_exp "/+" expression "+\\" slide_exp       -> sync_interrupt_exp
              | slide_exp

?slide_exp: slide_exp "[>" seq_exp -> slide_exp
          | seq_exp

?seq_exp: seq_exp ";" prefix_exp -> seq_exp
        | prefix_exp

// GPrefix: right-associative prefix / guard
?prefix_exp: decor_exp "->" prefix_exp -> prefix_exp
           | decor_exp "&"  prefix_exp -> guarded_exp
           | decor_exp

// Decoration: input (?), output (!), nondeterministic input ($)
?decor_exp: decor_exp "?" pattern (":" expression)? -> input_exp
          | decor_exp "!" dot_op_exp                 -> output_exp
          | decor_exp "$" pattern (":" expression)?  -> nondeterministic_input_exp
          | dot_op_exp

// DotExp is right-associative
?dot_op_exp: colon_exp "." dot_op_exp -> dot_op_exp
           | colon_exp

?colon_exp: or_exp ":" or_exp -> colon_exp
          | or_exp

?or_exp: or_exp "or" and_exp -> or_exp
       | and_exp

?and_exp: and_exp "and" not_exp -> and_exp
        | not_exp

// "not" as a binary operator (unusual; mirrors Xtext NotExp rule)
?not_exp: cmp_exp "not" cmp_exp -> not_exp
        | cmp_exp

?cmp_exp: cmp2_exp ">" cmp2_exp -> gt_exp
        | cmp2_exp

?cmp2_exp: add_exp "<=" add_exp -> leq_exp
         | add_exp "<"  add_exp -> lt_exp
         | add_exp ">=" add_exp -> geq_exp
         | add_exp "==" add_exp -> eq_exp
         | add_exp "!=" add_exp -> neq_exp
         | add_exp

?add_exp: add_exp "+" mul_exp -> plus_exp
        | add_exp "-" mul_exp -> minus_exp
        | mul_exp

?mul_exp: mul_exp "*" len_exp -> mult_exp
        | mul_exp "/" len_exp -> div_exp
        | mul_exp "%" len_exp -> mod_exp
        | len_exp

?len_exp: cat_exp "#" cat_exp -> list_len_exp
        | cat_exp

?cat_exp: cat_exp "^" rename_exp -> concat_exp
        | rename_exp

?rename_exp: project_exp "[[" renaming_pair ("," renaming_pair)* ("|" statement ("," statement)*)? "]]" -> rename_exp
           | project_exp

?project_exp: project_exp "|\\" atom_exp -> project_exp
            | atom_exp

renaming_pair: expression "<-" expression

// ── Atomic expressions ────────────────────────────────────────────────────────
?atom_exp: if_then_else
         | core_process
         | core_singleton
         | builtin_fn
         | "(" expression ")"                              -> paren_exp
         | "(" expression ("," expression)+ ")"           -> tuple_exp
         | pref
         | set_list_exp
         | INT                                             -> int_exp
         | "\\" pattern ("," pattern)* "@" expression     -> lambda_exp
         | STRING                                          -> string_exp
         | CHAR                                            -> char_exp
         | "(|" mapping ("," mapping)* "|)"               -> map_exp
         | ("True" | "true")                               -> true_exp
         | ("False" | "false")                             -> false_exp
         | "not" expression                                -> unary_not_exp
         | "Events"                                        -> events_exp
         | "Char"                                          -> char_type_exp
         | "Int"                                           -> int_type_exp
         | "Proc"                                          -> proc_type_exp
         | "Bool"                                          -> bool_type_exp

if_then_else  : "if" expression "then" expression "else" expression
core_singleton: "STOP" -> stop_exp
              | "SKIP"  -> skip_exp
core_process  : "CHAOS" "(" expression ")" -> chaos_exp
              | "RUN"   "(" expression ")" -> run_exp
              | "WAIT"  "(" expression ")" -> wait_exp

// ── Built-in functions (all alternatives in one rule) ────────────────────────
?builtin_fn: "error"  "(" expression ")" -> error_exp
           | "show"   "(" expression ")" -> show_exp
           | "card"   "(" expression ")" -> card_exp
           | "empty"  "(" expression ")" -> empty_exp
           | "Inter"  "(" expression ")" -> big_inter_exp
           | "seq"    "(" expression ")" -> seq_fn_exp
           | "Seq"    "(" expression ")" -> big_seq_exp
           | "Set"    "(" expression ")" -> set_of_exp
           | "Union"  "(" expression ")" -> big_union_exp
           | "concat" "(" expression ")" -> concat_fn_exp
           | "head"   "(" expression ")" -> head_exp
           | "length" "(" expression ")" -> length_exp
           | "null"   "(" expression ")" -> null_exp
           | "set"    "(" expression ")" -> set_fn_exp
           | "tail"   "(" expression ")" -> tail_exp
           | "emptyMap"          "(" expression ")"                              -> empty_map_exp
           | "mapDelete"         "(" expression ")"                              -> map_delete_exp
           | "mapFromList"       "(" expression ")"                              -> map_from_list_exp
           | "mapLookup"         "(" expression ")"                              -> map_lookup_exp
           | "mapMember"         "(" expression ")"                              -> map_member_exp
           | "mapToList"         "(" expression ")"                              -> map_to_list_exp
           | "mapUpdated"        "(" expression ")"                              -> map_update_exp
           | "mapUpdateMultiple" "(" expression ")"                              -> map_update_multi_exp
           | "chase"             "(" expression ")"                              -> chase_exp
           | "chase_nocache"     "(" expression ")"                              -> chase_nocache_exp
           | "deter"             "(" expression ")"                              -> deter_exp
           | "diamond"           "(" expression ")"                              -> diamond_exp
           | "dbisim"            "(" expression ")"                              -> dbisim_exp
           | "explicate"         "(" expression ")"                              -> explicate_exp
           | "lazyenumerate"     "(" expression ")"                              -> lazyenumerate_exp
           | "normal"            "(" expression ")"                              -> normal_exp
           | "sbisim"            "(" expression ")"                              -> sbisim_exp
           | "tau_loop_factor"   "(" expression ")"                              -> tau_loop_factor_exp
           | "timed_priority"    "(" expression ")"                              -> timed_priority_exp
           | "wbisim"            "(" expression ")"                              -> wbisim_exp
           | "mtransclose"              "(" expression ")"                       -> mtransclose_exp
           | "relational_image"         "(" expression ")"                       -> rel_image_exp
           | "relational_inverse_image" "(" expression ")"                       -> rel_inv_image_exp
           | "transpose"                "(" expression ")"                       -> transpose_exp
           | "extensions"               "(" expression ")"                       -> extensions_exp
           | "productions"              "(" expression ")"                       -> productions_exp
           | "diff"    "(" expression "," expression ")"                         -> diff_exp
           | "inter"   "(" expression "," expression ")"                         -> inter_exp
           | "member"  "(" expression "," expression ")"                         -> member_exp
           | "elem"    "(" expression "," expression ")"                         -> elem_exp
           | "union"   "(" expression "," expression ")"                         -> union_exp
           | "Map"     "(" expression "," expression ")"                         -> map_type_exp
           | "prioritise"         "(" expression "," expression ")"              -> prioritise_exp
           | "prioritise_nocache" "(" expression "," expression ")"              -> prioritise_nocache_exp
           | "failure_watchdog" "(" expression "," expression "," expression ")" -> failure_watchdog_exp
           | "trace_watchdog"   "(" expression "," expression "," expression ")" -> trace_watchdog_exp
           | "prioritisepo" "(" expression "," expression "," expression "," expression ")" -> prioritisepo_exp

// Process / function reference (most general — matched last among atom alternatives)
pref: qualified_name ("(" expression ("," expression)* ")")?

// ── Set / list / map expressions ─────────────────────────────────────────────
?set_list_exp: list_exp | ranged_list_exp | set_exp | ranged_set_exp | enum_set_exp

// Lists use cmp2_exp (not full expression) per the Xtext grammar comment:
// "a string such as <2>1> is ambiguous; we restrict to ComparisonExp2"
// We approximate with expression here; Earley handles the ambiguity.
list_exp       : "<" (expression ("," expression)*)? ("|" statement ("," statement)*)? ">"
ranged_list_exp: "<" expression ".." expression ("|" statement ("," statement)*)? ">"
set_exp        : "{" (expression ("," expression)*)? ("|" statement ("," statement)*)? "}"
ranged_set_exp : "{" expression ".." expression ("|" statement ("," statement)*)? "}"
enum_set_exp   : "{|" (expression ("," expression)*)? ("|" statement ("," statement)*)? "|}"

mapping: expression "=>" expression

// ── Statements (comprehension generators / predicates) ────────────────────────
?statement: generator_stmt | set_generator_stmt | predicate_stmt
generator_stmt    : pattern "<-" expression
set_generator_stmt: pattern ":" expression
predicate_stmt    : expression

// ── Type annotations ──────────────────────────────────────────────────────────
type_annotation: validid ("," validid)* "::" type_constraint_prefix? type_constructor

?type_constraint_prefix: constraint "=>"
                       | "(" constraint ("," constraint)+ ")" "=>"

type_constructor: type_expr
               | type_constructor "."   type_constructor -> dot_type
               | type_constructor "=>"  type_constructor -> dotable_type
               | type_constructor "=>*" type_constructor -> extendable_type
               | type_constructor "->"  type_constructor -> fn_type

?type_expr: type_variable
          | "{" type_constructor "}"                              -> set_type
          | "(|" type_constructor "=>" type_constructor "|)"     -> map_type_ann
          | "<" type_constructor ">"                              -> seq_type
          | "(" type_constructor ("," type_constructor)+ ")"     -> tuple_type
          | "Int"   -> int_type
          | "Bool"  -> bool_type
          | "Char"  -> char_type
          | "Event" -> event_type
          | "Proc"  -> proc_type_lit

type_variable: validid
constraint: type_constraint_kw type_variable
?type_constraint_kw: "Eq" | "Complete" | "Ord" | "Set" | "Yieldable"
"""

# ---------------------------------------------------------------------------
# Parser instance (lazy-initialised)
# ---------------------------------------------------------------------------

_parser: Lark | None = None


def _get_parser() -> Lark:
    global _parser
    if _parser is None:
        _parser = Lark(
            GRAMMAR,
            parser="earley",
            ambiguity="resolve",
            start="cspm",
            propagate_positions=True,
        )
    return _parser


def parse(src: str) -> Tree:
    """Parse a CSP-M source string and return the lark Tree.

    Each Tree node has a ``meta`` attribute with ``line``, ``column``,
    ``end_line``, and ``end_column`` populated (1-based).
    """
    return _get_parser().parse(src)


# ---------------------------------------------------------------------------
# Source-span helpers
# ---------------------------------------------------------------------------

def span_of(node: Tree | Token) -> tuple[int, int, int, int]:
    """Return (line, col, end_line, end_col) for a tree node or token."""
    if isinstance(node, Tree):
        m = node.meta
        return m.line, m.column, m.end_line, m.end_column
    # Token
    return node.line, node.column, node.end_line, node.end_column


def source_text(src: str, node: Tree | Token) -> str:
    """Extract the original source text for the given parse-tree node.

    lark reports 1-indexed line numbers and 1-indexed column numbers for
    Tree.meta positions (via propagate_positions=True).  end_column is one
    past the last character (exclusive), so the correct Python slice is
    [col-1 : end_col-1].
    """
    lines = src.splitlines(keepends=True)
    line, col, end_line, end_col = span_of(node)
    s, e = col - 1, end_col - 1      # convert to 0-based indices
    if line == end_line:
        return lines[line - 1][s:e]
    parts = [lines[line - 1][s:]]
    for ln in range(line + 1, end_line):
        parts.append(lines[ln - 1])
    parts.append(lines[end_line - 1][:e])
    return "".join(parts)


# ---------------------------------------------------------------------------
# Higher-level utilities for resolving anonymous sub-processes
# ---------------------------------------------------------------------------

_PARALLEL_NODE_TYPES = frozenset({
    "gen_par_exp",
    "alpha_par_exp",
    "linked_par_exp",
    "exception_exp",
    "interleave_exp",
})


def _is_bare_pref(node: Tree) -> bool:
    """True if node is a plain process/variable reference with no call args.

    pref: qualified_name ("(" expression* ")")?
    A bare pref has only the qualified_name child (one child total).
    """
    return isinstance(node, Tree) and node.data == "pref" and len(node.children) == 1


def _operand_label(src: str, node: Tree) -> str:
    """Short label for a parallel operand.

    Bare process references (P, Q, MutexA, …) use their name directly.
    Everything else is shown as trimmed source text.
    """
    if _is_bare_pref(node):
        parts: list[str] = [str(tok) for tok in node.scan_values(lambda _: True)]
        return "::".join(parts)
    import re
    return re.sub(r"\s+", " ", source_text(src, node).strip())


def parallel_operand_labels(src: str) -> dict[str, list[str]]:
    """Return {process_name: [label_left, label_right]} for each top-level
    definition whose RHS contains an outermost parallel composition.

    Labels are human-readable: simple process references use their name;
    complex sub-expressions are shown as their source text in parentheses.
    """
    t = parse(src)
    result: dict[str, list[str]] = {}

    for child in t.children:
        if not (isinstance(child, Tree) and child.data == "function_def"):
            continue
        name_validid = child.children[0]
        name = str(next(name_validid.scan_values(lambda _: True)))
        expr_node = child.children[-1]

        outer_par = _find_outermost_parallel(expr_node)
        if outer_par is None:
            continue

        operands = _parallel_operands(outer_par)
        result[name] = [_operand_label(src, op) for op in operands]

    return result


def _count_prefix_chain(node: Tree | Token) -> tuple[int, str | None]:
    """Count '->' prefix steps leading to a bare named-process call.

    Returns (count, continuation_name) for a chain of the form
        e1 -> e2 -> ... -> eN -> P
    where P is a bare process reference (no call arguments).
    Returns (0, None) if the expression is not a simple chain of this form.
    """
    if not isinstance(node, Tree):
        return 0, None
    # Strip transparent 'expression' wrapper
    if node.data == "expression":
        if len(node.children) == 1:
            return _count_prefix_chain(node.children[0])
        return 0, None
    if node.data != "prefix_exp" or len(node.children) != 2:
        return 0, None
    _, cont = node.children  # first child is the event; only the continuation matters
    if isinstance(cont, Tree) and cont.data == "pref" and _is_bare_pref(cont):
        # Terminal: a bare process call P
        qn = cont.children[0]
        if isinstance(qn, Tree) and qn.data == "qualified_name":
            vid = qn.children[0]
            if isinstance(vid, Tree) and vid.data == "validid":
                return 1, str(vid.children[0])
    elif isinstance(cont, Tree) and cont.data == "prefix_exp":
        sub_count, sub_cont = _count_prefix_chain(cont)
        if sub_cont is not None:
            return 1 + sub_count, sub_cont
    return 0, None


def sequential_tail(src: str) -> dict[str, tuple[int, str]]:
    """For each parameter-free process definition that is a pure sequential
    prefix chain ending in a bare named-process call, return
    {process_name: (prefix_event_count, continuation_process_name)}.

    Only considers definitions of the form:
        P = e1 -> e2 -> ... -> eN -> Q
    where Q is a bare identifier with no arguments.
    """
    t = _get_parser().parse(src)
    result: dict[str, tuple[int, str]] = {}
    for child in t.children:
        if not isinstance(child, Tree) or child.data != "function_def":
            continue
        if len(child.children) != 2:  # skip parameterised definitions
            continue
        name = str(next(child.children[0].scan_values(lambda _: True)))
        count, cont = _count_prefix_chain(child.children[1])
        if cont is not None:
            result[name] = (count, cont)
    return result


def _find_outermost_parallel(node: Tree) -> Tree | None:
    """Pre-order search: return the first parallel-operator node, or None."""
    if isinstance(node, Tree):
        if node.data in _PARALLEL_NODE_TYPES:
            return node
        for child in node.children:
            found = _find_outermost_parallel(child)
            if found is not None:
                return found
    return None


def _parallel_operands(par_node: Tree) -> list[Tree]:
    """Extract [left_operand, right_operand] from a parallel parse-tree node.

    All parallel node types store the left and right process expressions as the
    first and last Tree children; the synchronisation set / links sit between.
    """
    tree_children = [c for c in par_node.children if isinstance(c, Tree)]
    if len(tree_children) >= 2:
        return [tree_children[0], tree_children[-1]]
    if len(tree_children) == 1:
        return [tree_children[0]]
    return []
