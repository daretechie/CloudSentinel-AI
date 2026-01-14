import { describe, it, expect } from 'vitest';
import { cn } from './utils';

describe('cn utility', () => {
	it('merges class names correctly', () => {
		expect(cn('btn', 'btn-primary')).toBe('btn btn-primary');
	});

	it('handles conditional classes', () => {
		expect(cn('btn', true && 'active', false && 'hidden')).toBe('btn active');
	});

	it('resolves tailwind conflicts', () => {
		// p-4 and p-2 conflict, p-2 should win if it comes later
		expect(cn('p-4', 'p-2')).toBe('p-2');
		expect(cn('text-red-500', 'text-blue-500')).toBe('text-blue-500');
	});

	it('handles undefined and null', () => {
		expect(cn('btn', undefined, null)).toBe('btn');
	});
});
