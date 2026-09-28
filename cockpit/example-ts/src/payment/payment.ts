export interface PaymentResult {
  ok: boolean;
}

export function authorize(amount: number): PaymentResult {
  return { ok: amount > 0 };
}
