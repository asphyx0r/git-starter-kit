'use strict';

const utils = require('./utils');

module.exports = (ast, options = {}) => {
  const output = [];
  const active = new WeakSet();
  const stack = [{ node: ast }];
  while (stack.length) {
    const frame = stack.pop();
    const { node } = frame;
    if (frame.exit) {
      active.delete(node);
      continue;
    }
    // Upstream stringify does not pass parent context to child calls.
    const invalidBlock = options.escapeInvalid && utils.isInvalidBrace({});
    const invalidNode = node.invalid === true && options.escapeInvalid === true;
    if (node.value) {
      output.push((invalidBlock || invalidNode) && utils.isOpenOrClose(node)
        ? '\\' + node.value : node.value);
    } else if (node.nodes) {
      if (active.has(node)) throw new RangeError('Cyclic brace AST');
      active.add(node);
      stack.push({ node, exit: true });
      for (let i = node.nodes.length - 1; i >= 0; i--) {
        stack.push({ node: node.nodes[i] });
      }
    }
  }
  return output.join('');
};
