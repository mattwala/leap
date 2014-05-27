"""A flow-graph based intermediate representation"""

__copyright__ = "Copyright (C) 2014 Matt Wala"

__license__ = """
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

from .expressions import string_mapper
from pytools import RecordWithoutPickling, memoize_method
from leap.vm.utils import get_unique_name, get_variables, is_state_variable
from leap.vm.language import AssignExpression, AssignRHS
from textwrap import TextWrapper
from cgi import escape


class Inst(RecordWithoutPickling):
    """Base class for instructions in the ControlFlowGraph."""

    def __init__(self, **kwargs):
        if 'block' not in kwargs:
            kwargs['block'] = None
        assert 'terminal' in kwargs
        super(Inst, self).__init__(**kwargs)

    def set_block(self, block):
        self.block = block

    def get_defined_variables(self):
        """Returns the set of variables defined by this instruction."""
        raise NotImplementedError()

    def get_used_variables(self):
        """Returns the set of variables used by this instruction."""
        raise NotImplementedError()

    def get_jump_targets(self):
        """Returns the set of basic blocks that this instruction may jump to.
        """
        raise NotImplementedError()


class BranchInst(Inst):
    """A conditional branch."""

    def __init__(self, condition, on_true, on_false, block=None):
        super(BranchInst, self).__init__(condition=condition, on_true=on_true,
                                         on_false=on_false, block=block,
                                         terminal=True)

    def get_defined_variables(self):
        return frozenset()

    @memoize_method
    def get_used_variables(self):
        return get_variables(self.condition)

    def get_jump_targets(self):
        return frozenset([self.on_true, self.on_false])

    def __str__(self):
        return 'if %s then goto block %d else goto block %d' % (string_mapper(
            self.condition), self.on_true.number, self.on_false.number)


class AssignInst(Inst):
    """Assigns a value."""

    def __init__(self, assignment, block=None):
        """
        The inner assignment may be in these forms:

            - a (var, expr) tuple, where var is a string and expr is a
                pymbolic expression.

            - One of the following instruction types: AssignExpression,
                AssignRHS, AssignSolvedRHS, AssignDotProduct, AssignNorm
        """
        super(AssignInst, self).__init__(assignment=assignment, block=block,
                                         terminal=False)

    @memoize_method
    def get_defined_variables(self):
        if isinstance(self.assignment, tuple):
            return frozenset([self.assignment[0]])
        else:
            return self.assignment.get_assignees()

    @memoize_method
    def get_used_variables(self):
        if isinstance(self.assignment, tuple):
            return get_variables(self.assignment[1])
        else:
            return self.assignment.get_read_variables()

    def get_jump_targets(self):
        return frozenset()

    def __str__(self):
        assignment = self.assignment
        if isinstance(assignment, tuple):
            return '%s <- %s' % (assignment[0], string_mapper(assignment[1]))
        elif isinstance(assignment, AssignExpression):
            return '%s <- %s' % (assignment.assignee,
                                 string_mapper(assignment.expression))
        elif isinstance(assignment, AssignRHS):
            lines = []
            time = string_mapper(assignment.t)
            rhs = assignment.component_id
            for assignee, arguments in \
                    zip(assignment.assignees, assignment.rhs_arguments):
                arg_list = []
                for arg_pair in arguments:
                    name = arg_pair[0]
                    expr = string_mapper(arg_pair[1])
                    arg_list.append('%s=%s' % (name, expr))
                args = ', '.join(arg_list)
                if len(args) == 0:
                    lines.append('%s <- %s(%s)' % (assignee, rhs, time))
                else:
                    lines.append('%s <- %s(%s, %s)' %
                                 (assignee, rhs, time, args))
            return '\n'.join(lines)


class JumpInst(Inst):
    """Jumps to another basic block."""

    def __init__(self, dest, block=None):
        super(JumpInst, self).__init__(dest=dest, block=block, terminal=True)

    def get_defined_variables(self):
        return frozenset()

    def get_used_variables(self):
        return frozenset()

    def get_jump_targets(self):
        return frozenset([self.dest])

    def __str__(self):
        return 'goto block %d' % self.dest.number


class ReturnInst(Inst):
    """Returns from the function."""

    def __init__(self, expression, block=None):
        super(ReturnInst, self).__init__(expression=expression, block=block,
                                         terminal=True)

    def get_defined_variables(self):
        return frozenset()

    @memoize_method
    def get_used_variables(self):
        return get_variables(self.expression)

    def get_jump_targets(self):
        return frozenset()

    def __str__(self):
        return 'return %s' % string_mapper(self.expression)


class UnreachableInst(Inst):
    """Indicates an unreachable point in the code."""

    def __init__(self, block=None):
        super(UnreachableInst, self).__init__(block=block, terminal=True)

    def get_defined_variables(self):
        return frozenset()

    def get_used_variables(self):
        return frozenset()

    def get_jump_targets(self):
        return frozenset()

    def __str__(self):
        return 'unreachable'


class BasicBlock(object):
    """A maximal straight-line sequence of instructions."""

    def __init__(self, number, symbol_table):
        self.code = []
        self.predecessors = set()
        self.successors = set()
        self.terminated = False
        self.number = number
        self.symbol_table = symbol_table

    def __iter__(self):
        return iter(self.code)

    def __len__(self):
        return len(self.code)

    def clear(self):
        """Unregisters all instructions."""
        self.delete_instructions(self.code)

    def add_instruction(self, instruction):
        """Appends the given instruction to the code."""
        self.add_instructions([instruction])

    def add_instructions(self, instructions):
        """Appends the given instructions to the code."""
        for instruction in instructions:
            assert not self.terminated
            self.code.append(instruction)
            instruction.set_block(self)
            self.symbol_table.register_instruction(instruction)
            if instruction.terminal:
                # Update the successor information.
                self.terminated = True
                for successor in instruction.get_jump_targets():
                    self.add_successor(successor)

    def delete_instruction(self, instruction):
        """Deletes references to the given instruction."""
        self.delete_instructions([instruction])

    def delete_instructions(self, to_delete):
        """Deletes references to the given instructions."""
        new_code = []
        for inst in self.code:
            if inst not in to_delete:
                new_code.append(inst)
            else:
                self.symbol_table.unregister_instruction(inst)
                if inst.terminal:
                    # If we have removed the terminator, then also update the
                    # successors.
                    self.terminated = False
                    for successor in self.successors:
                        successor.predecessors.remove(self)
                    self.succesors = set()
        self.code = new_code

    def add_unreachable(self):
        """Appends an unreachable instruction to the block."""
        assert not self.terminated
        self.code.append(UnreachableInst(self))
        self.terminated = True

    def add_successor(self, successor):
        """Adds a successor block to the set of successors."""
        assert isinstance(successor, BasicBlock)
        self.successors.add(successor)
        successor.predecessors.add(self)

    def add_assignment(self, instruction):
        """Appends an assignment instruction to the block."""
        assert isinstance(instruction, tuple) or \
            isinstance(instruction, AssignExpression) or \
            isinstance(instruction, AssignRHS)
        self.add_instruction(AssignInst(instruction))

    def add_jump(self, dest):
        """Appends a jump instruction to the block with the given destination.
        """
        self.add_instruction(JumpInst(dest))

    def add_branch(self, condition, on_true, on_false):
        """Appends a branch to the block with the given condition and
        destinations."""
        self.add_instruction(BranchInst(condition, on_true, on_false))

    def add_return(self, expr):
        """Appends a return instruction to the block that returns the given
        expression."""
        self.add_instruction(ReturnInst(expr))

    def __str__(self):
        lines = []
        lines.append('===== basic block %s =====' % self.number)
        lines.extend(str(inst) for inst in self.code)
        return '\n'.join(lines)


class ControlFlowGraph(object):
    """A control flow graph of BasicBlocks."""

    def __init__(self, start_block):
        self.start_block = start_block
        self.symbol_table = start_block.symbol_table
        self.update()

    def is_acyclic(self):
        """Returns true if the control flow graph contains no loops."""
        return self.acyclic

    def update(self):
        """Traverse the graph and construct the set of basic blocks."""
        self.postorder_traversal = []
        stack = [self.start_block]
        visiting = set()
        visited = set()
        acyclic = True
        while len(stack) > 0:
            top = stack[-1]
            if top not in visited:
                # Mark top as being visited. Add the children of top to the
                # stack.
                visited.add(top)
                visiting.add(top)
                for successor in top.successors:
                    if successor in visiting:
                        acyclic = False
                    elif successor not in visited:
                        stack.append(successor)
            else:
                if top in visiting:
                    # Finished visiting top. Append it to the traversal.
                    visiting.remove(top)
                    self.postorder_traversal.append(top)
                stack.pop()
        self.acyclic = acyclic

    def __iter__(self):
        return self.postorder()

    def __len__(self):
        return len(self.postorder_traversal)

    def postorder(self):
        """Returns an iterator to a postorder traversal of the set of basic
        blocks."""
        return iter(self.postorder_traversal)

    def reverse_postorder(self):
        """Returns an iterator to a reverse postorder traversal of the set of
        basic blocks."""
        return reversed(self.postorder_traversal)

    def get_dot_graph(self):
        """Return a string in the graphviz language that represents the control
        flow graph."""
        # Wrap long lines.
        wrapper = TextWrapper(width=80, subsequent_indent=4 * ' ')

        lines = []
        lines.append('digraph ControlFlowGraph {')

        # Draw the basic blocks.
        for block in self:
            name = str(block.number)

            # Draw the block number.
            lines.append('%s [shape=box,label=<' % name)
            lines.append('<table border="0">')
            lines.append('<tr>')
            lines.append('<td align="center"><font face="Helvetica">')
            lines.append('<b>basic block %s</b>' % name)
            lines.append('</font></td>')
            lines.append('</tr>')

            # Draw the code.
            for inst in block:
                for line in wrapper.wrap(str(inst)):
                    lines.append('<tr>')
                    lines.append('<td align="left">')
                    lines.append('<font face="Courier">')
                    lines.append(escape(line).replace(' ', '&nbsp;'))
                    lines.append('</font>')
                    lines.append('</td>')
                    lines.append('</tr>')
            lines.append('</table>>]')

            # Draw the successor edges.
            for successor in block.successors:
                lines.append('%s -> %d;' % (name, successor.number))

        # Add a dummy entry to mark the start block.
        lines.append('entry [style=invisible];')
        lines.append('entry -> %d;' % self.start_block.number)

        lines.append('}')
        return '\n'.join(lines)

    def __str__(self):
        return '\n'.join(map(str, self.reverse_postorder()))


class FlagAnalysis(object):
    """Keeps track of the values of a set of boolean flags."""

    def __init__(self, flags):
        """Creates a flag analysis object that keeps track of the given set of
        flags."""
        self.all_flags = set(flags)
        self.must_be_true = set()
        self.must_be_false = set()

    def set_true(self, flag):
        """Returns a new flag analysis object with the given flag set to true.
        """
        assert flag in self.all_flags
        import copy
        new_fa = copy.deepcopy(self)
        new_fa.must_be_true.add(flag)
        new_fa.must_be_false.discard(flag)
        return new_fa

    def set_false(self, flag):
        """Returns a new flag analysis object with the given flag set to false.
        """
        assert flag in self.all_flags
        import copy
        new_fa = copy.deepcopy(self)
        new_fa.must_be_false.add(flag)
        new_fa.must_be_true.discard(flag)
        return new_fa

    def is_definitely_true(self, flag):
        """Determines if the flag must be set to true."""
        assert flag in self.all_flags
        return flag in self.must_be_true

    def is_definitely_false(self, flag):
        """Determines if the flag must be set to false."""
        assert flag in self.all_flags
        return flag in self.must_be_false

    def __and__(self, other):
        """Returns a new flag analysis that represents the conjunction of the
        inputs."""
        assert isinstance(other, FlagAnalysis)
        assert self.all_flags == other.all_flags
        new_fa = FlagAnalysis(self.all_flags)
        new_fa.must_be_true = self.must_be_true & other.must_be_true
        new_fa.must_be_false = self.must_be_false & other.must_be_false
        return new_fa


class SymbolTable(object):
    """Holds information regarding the variables in a code fragment."""

    class SymbolTableEntry(RecordWithoutPickling):
        """Holds information about the contents of a variable. This includes
        all instructions that reference the variable."""

        def __init__(self, *attrs):
            all_attrs = ['is_global', 'is_return_value', 'is_flag']
            attr_dict = dict((attr, attr in attrs) for attr in all_attrs)
            super(SymbolTable.SymbolTableEntry, self).__init__(attr_dict)
            self.references = set()

        @property
        def is_unreferenced(self):
            """Returns whether this variable is not referenced by any
            instructions."""
            return len(self.references) == 0

        def add_reference(self, inst):
            """Add an instruction to the list of instructions that reference
            this variable."""
            self.references.add(inst)

        def remove_reference(self, inst):
            """Remove an instruction from the list of instructions that
            reference this variable."""
            self.references.discard(inst)

    def __init__(self):
        self.block_ids = None
        self.variables = {}
        self.named_variables = set()

    def register_instruction(self, inst):
        variables = inst.get_defined_variables() | inst.get_used_variables()
        for variable in variables:
            assert variable in self.variables
            self.variables[variable].add_reference(inst)

    def unregister_instruction(self, inst):
        variables = inst.get_defined_variables() | inst.get_used_variables()
        for variable in variables:
            assert variable in self.variables
            self.variables[variable].remove_reference(inst)
            if self.variables[variable].is_unreferenced:
                del self.variables[variable]

    def __iter__(self):
        return iter(self.variables)

    def __getitem__(self, var):
        return self.variables[var]

    def add_variable(self, var, *attrs):
        self.variables[var] = SymbolTable.SymbolTableEntry(*attrs)
        self.named_variables.add(var)

    def get_fresh_variable_name(self, prefix):
        name = get_unique_name(prefix, self.named_variables)
        self.named_variables.add(name)
        return name
