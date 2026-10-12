'use strict';

const fill = require('fill-range');
const stringify = require('./stringify');
const utils = require('./utils');

const append = (queue = '', stash = '', enclose = false) => {
  const frames = [];
  const queueArrays = new WeakSet();
  const stashArrays = new WeakSet();
  let answer;

  const finish = (frame, result) => {
    if (frame.activeArray) frame.activeSet.delete(frame.activeArray);
    if (frames.length) frames[frames.length - 1].result.push(result);
    else answer = result;
  };
  const enter = (q = '', s = '', wrapped = false, activeArray, activeSet) => {
    if (activeArray) {
      if (activeSet.has(activeArray)) throw new RangeError('Cyclic brace queue');
      activeSet.add(activeArray);
    }
    const frame = {
      queue: [].concat(q), stash: [].concat(s), enclose: wrapped,
      result: [], item: 0, value: 0, element: 0, activeArray, activeSet
    };
    if (!frame.stash.length) finish(frame, frame.queue);
    else if (!frame.queue.length) {
      finish(frame, wrapped ? utils.flatten(frame.stash).map(ele => `{${ele}}`) : frame.stash);
    } else frames.push(frame);
  };

  enter(queue, stash, enclose);
  while (frames.length) {
    const frame = frames[frames.length - 1];
    if (frame.item === frame.queue.length) {
      frames.pop();
      finish(frame, utils.flatten(frame.result));
      continue;
    }
    const item = frame.queue[frame.item];
    if (Array.isArray(item)) {
      if (frame.value === item.length) {
        frame.item++;
        frame.value = 0;
      } else enter(item[frame.value++], frame.stash, frame.enclose, item, queueArrays);
    } else if (frame.element === frame.stash.length) {
      frame.item++;
      frame.element = 0;
    } else {
      let ele = frame.stash[frame.element++];
      if (frame.enclose && typeof ele === 'string') ele = `{${ele}}`;
      if (Array.isArray(ele)) enter(item, ele, frame.enclose, ele, stashArrays);
      else frame.result.push(item + ele);
    }
  }
  return answer;
};

const expand = (ast, options = {}) => {
  const rangeLimit = options.rangeLimit === undefined ? 1000 : options.rangeLimit;
  const frames = [];
  const active = new WeakSet();

  const enter = (node, parent = {}) => {
    if (active.has(node)) throw new RangeError('Cyclic brace AST');
    node.queue = [];
    let p = parent;
    let q = parent.queue;
    while (p.type !== 'brace' && p.type !== 'root' && p.parent) {
      p = p.parent;
      q = p.queue;
    }
    if (node.invalid || node.dollar) {
      q.push(append(q.pop(), stringify(node, options)));
      return;
    }
    if (node.type === 'brace' && node.invalid !== true && node.nodes.length === 2) {
      q.push(append(q.pop(), ['{}']));
      return;
    }
    if (node.nodes && node.ranges > 0) {
      const args = utils.reduce(node.nodes);
      if (utils.exceedsLimit(...args, options.step, rangeLimit)) {
        throw new RangeError('expanded array length exceeds range limit. Use options.rangeLimit to increase or disable the limit.');
      }
      let range = fill(...args, options);
      if (range.length === 0) range = stringify(node, options);
      q.push(append(q.pop(), range));
      node.nodes = [];
      return;
    }
    const enclose = utils.encloseBrace(node);
    let queue = node.queue;
    let block = node;
    while (block.type !== 'brace' && block.type !== 'root' && block.parent) {
      block = block.parent;
      queue = block.queue;
    }
    active.add(node);
    frames.push({ node, q, queue, enclose, index: 0 });
  };

  enter(ast);
  while (frames.length) {
    const frame = frames[frames.length - 1];
    if (frame.index === frame.node.nodes.length) {
      active.delete(frame.node);
      frames.pop();
      continue;
    }
    const index = frame.index++;
    const child = frame.node.nodes[index];
    if (child.type === 'comma' && frame.node.type === 'brace') {
      if (index === 1) frame.queue.push('');
      frame.queue.push('');
    } else if (child.type === 'close') {
      frame.q.push(append(frame.q.pop(), frame.queue, frame.enclose));
    } else if (child.value && child.type !== 'open') {
      frame.queue.push(append(frame.queue.pop(), child.value));
    } else if (child.nodes) enter(child, frame.node);
  }
  return utils.flatten(ast.queue);
};

module.exports = expand;
