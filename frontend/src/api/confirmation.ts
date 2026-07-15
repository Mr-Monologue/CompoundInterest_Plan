import { api } from './client';
import type { DecisionRequest } from '../types/productCore';

export function submitDecision(itemId: number, data: DecisionRequest): Promise<any> {
  return api.post(`/api/weekly-plan-items/${itemId}/decision`, data);
}

export function getDecision(itemId: number): Promise<any> {
  return api.get(`/api/weekly-plan-items/${itemId}/decision`);
}
