import crypto from 'crypto';

const SECRET_KEY = process.env.CLUSTER_SECRET || 'your-cluster-hmac-secret';

/**
 * Validates and decodes the client token in-memory using HMAC-SHA512.
 */
export function verifyClientToken(tokenHeader) {
  if (!tokenHeader) {
    throw new Error('Access Denied: Missing client token.');
  }

  const [encodedPayload, clientSignature] = tokenHeader.split('.');
  if (!encodedPayload || !clientSignature) {
    throw new Error('Access Denied: Malformed token structure.');
  }

  const payloadString = Buffer.from(encodedPayload, 'base64').toString('utf8');
  
  const expectedSignature = crypto
    .createHmac('sha512', SECRET_KEY)
    .update(payloadString)
    .digest('hex');

  const isValid = crypto.timingSafeEqual(
    Buffer.from(expectedSignature, 'hex'),
    Buffer.from(clientSignature, 'hex')
  );

  if (!isValid) {
    throw new Error('Access Denied: Invalid cryptographic token signature.');
  }

  const payload = JSON.parse(payloadString);

  if (Date.now() > payload.exp) {
    throw new Error('Access Denied: Subscription token has expired.');
  }

  return payload;
}
