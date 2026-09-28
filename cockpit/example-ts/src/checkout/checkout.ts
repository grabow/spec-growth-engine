import { authorize } from "../payment/payment";
import { log } from "../util/log";

export interface Cart {
  total: number;
}

export interface Order {
  total: number;
  authorized: boolean;
}

export function createOrder(cart: Cart): Order {
  log("createOrder called");
  const result = authorize(cart.total);
  return { total: cart.total, authorized: result.ok };
}
