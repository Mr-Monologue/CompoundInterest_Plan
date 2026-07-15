import { api } from './client';
import type { WeeklyInvestmentPlan, PlanBuildRequest, PlanFreezeResult } from '../types/productCore';

export function getWeeklyPlans(): Promise<WeeklyInvestmentPlan[]> {
  return api.get('/api/weekly-plans');
}

export function getWeeklyPlan(planId: number): Promise<WeeklyInvestmentPlan & { items: any[] }> {
  return api.get(`/api/weekly-plans/${planId}`);
}

export function buildWeeklyPlan(data: PlanBuildRequest): Promise<any> {
  return api.post('/api/weekly-plans/build', data);
}

export function freezeWeeklyPlan(planId: number): Promise<PlanFreezeResult> {
  return api.post(`/api/weekly-plans/${planId}/freeze`);
}
