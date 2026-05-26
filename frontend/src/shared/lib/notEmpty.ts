export const notEmpty = <T>(value: T | null | undefined): value is T => {
    if (value instanceof Array) return value.length > 0;
    if (value instanceof Number) return !Number.isNaN(value);

    return (
        typeof value !== "undefined" &&
        value !== null &&
        value !== ""
    );
};
