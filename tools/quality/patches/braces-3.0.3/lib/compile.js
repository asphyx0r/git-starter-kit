'use strict';

const fill = require('fill-range');
const utils = require('./utils');

const compile = (ast, options = {}) => {
  const output = [];
  const active = new WeakSet();
  const stack = [{ node: ast, parent: {} }];

  while (stack.length) {
    const frame = stack.pop();
    const { node, parent } = frame;
    if (frame.exit) {
      active.delete(node);
      continue;
    }
    const invalidBlock = utils.isInvalidBrace(parent);
    const invalidNode = node.invalid === true && options.escapeInvalid === true;
    const invalid = invalidBlock === true || invalidNode === true;
    const prefix = options.escapeInvalid === true ? '\\' : '';

    if (node.isOpen === true) {
      output.push(prefix + node.value);
    } else if (node.isClose === true) {
      console.log('node.isClose', prefix, node.value);
      output.push(prefix + node.value);
    } else if (node.type === 'open') {
      output.push(invalid ? prefix + node.value : '(');
    } else if (node.type === 'close') {
      output.push(invalid ? prefix + node.value : ')');
    } else if (node.type === 'comma') {
      output.push(node.prev.type === 'comma' ? '' : invalid ? node.value : '|');
    } else if (node.value) {
      output.push(node.value);
    } else {
      if (node.nodes && node.ranges > 0) {
        const args = utils.reduce(node.nodes);
        const range = fill(...args, { ...options, wrap: false, toRegex: true, strictZeros: true });
        if (range.length !== 0) {
          output.push(args.length > 1 && range.length > 1 ? `(${range})` : range);
          continue;
        }
      }
      if (node.nodes) {
        if (active.has(node)) throw new RangeError('Cyclic brace AST');
        active.add(node);
        stack.push({ node, exit: true });
        for (let i = node.nodes.length - 1; i >= 0; i--) {
          stack.push({ node: node.nodes[i], parent: node });
        }
      }
    }
  }
  return output.join('');
};

module.exports = compile;
