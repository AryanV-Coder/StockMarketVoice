from fastapi import APIRouter, HTTPException, Path
from supabase.direct_supabase_connection import connect_postgres

router = APIRouter(
    prefix="/clients",
    tags=["clients"]
)

@router.get("/dummy_data/{phone_number}")
def get_client_dummy_data(phone_number: int = Path(..., description="Phone number of the client")):
    """
    Retrieve the stock name, quantity, average rate, and stock price value from the table public.clients_dummy_data for a given phone number.
    """
    conn_result = connect_postgres()
    if not conn_result:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    connection, cursor = conn_result
    
    try:
        query = "SELECT stock_name, quantity, avg_rate, stock_buy_value FROM public.clients_dummy_data WHERE phone_number = %s;"
        cursor.execute(query, (phone_number,))
        
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        
        return {
            "status": "success",
            "columns": columns,
            "rows": rows
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        connection.close()

@router.get("/")
def get_all_clients():
    """
    Retrieve all the clients from the table public.clients.
    """
    conn_result = connect_postgres()
    if not conn_result:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    connection, cursor = conn_result
    
    try:
        query = "SELECT * FROM public.clients;"
        cursor.execute(query)
        
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        
        result = [dict(zip(columns, row)) for row in rows]
        
        return {"status": "success", "data": result}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        connection.close()
